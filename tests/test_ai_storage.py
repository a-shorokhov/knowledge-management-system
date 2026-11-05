import os
import unittest

from alembic import command
from pgvector.sqlalchemy import VECTOR
import sqlalchemy as sa
from sqlalchemy.orm import Session

import test_schema_upgrade as migrations
import test_erd as runtime
from models.document_chunks import DocumentChunk
from models.ai_retrospectives import AIRetrospective


class AIStorageModelTests(unittest.TestCase):
    def test_embedding_is_native_vector_256_without_search_index(self):
        column = DocumentChunk.__table__.c.embedding
        self.assertIsInstance(column.type, VECTOR)
        self.assertEqual(column.type.dim, 256)
        self.assertTrue(column.nullable)
        self.assertEqual(str(column.type.compile(dialect=sa.dialects.postgresql.dialect())), 'VECTOR(256)')
        self.assertEqual(DocumentChunk.__table__.indexes, set())


@unittest.skipUnless(os.environ.get('KMS_TEST_DATABASE_URL'), 'Нужен отдельный PostgreSQL 18 с pgvector: KMS_TEST_DATABASE_URL')
class AIStoragePostgreSQLTests(unittest.TestCase):
    setUp = migrations.PostgreSQLMigrationTests.setUp
    connect = migrations.PostgreSQLMigrationTests.connect
    tearDown = migrations.PostgreSQLMigrationTests.tearDown
    upgrade = migrations.PostgreSQLMigrationTests.upgrade
    assert_current = migrations.PostgreSQLMigrationTests.assert_current
    legacy_data = migrations.PostgreSQLMigrationTests.legacy_data

    def prepare(self):
        self.legacy_data()
        self.upgrade()
        version = int(self.connection.scalar(sa.text('SHOW server_version_num')))
        self.assertTrue(180000 <= version < 190000)
        self.assertIsNotNone(self.connection.scalar(sa.text("SELECT extversion FROM pg_extension WHERE extname='vector'")))
        self.connection.commit()

    def test_previous_schema_rows_survive_upgrade_and_repeat(self):
        self.legacy_data()
        self.connection.commit()
        command.upgrade(migrations.migration_config(self.connection), '0003_notes_reflections')
        self.connection.execute(sa.text('UPDATE launch_designs SET data=CAST(:data AS jsonb)'),
                                {"data": '{"passport":{"category":"Keep"}}'})
        self.connection.execute(sa.text("INSERT INTO launch_reflections (launch_id,what_went_well) VALUES (1,'Keep reflection')"))
        self.connection.commit()
        names = set(runtime.database.Base.metadata.tables) - {'document_chunks', 'ai_retrospectives'}
        before = {name: self.connection.execute(sa.text(f'SELECT * FROM {name} ORDER BY 1')).all() for name in names}
        self.connection.commit()
        self.upgrade()
        self.upgrade()
        after = {name: self.connection.execute(sa.text(f'SELECT * FROM {name} ORDER BY 1')).all() for name in names}
        self.assertEqual(before, after)
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM document_chunks')), 0)
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM ai_retrospectives')), 0)
        self.assert_current()

    def test_native_vector_roundtrip_256_and_null(self):
        self.prepare()
        with Session(bind=self.connection) as session:
            session.add_all([
                DocumentChunk(stored_file_id=1, chunk_index=0, content='First', embedding=[0.5, 1.0, -2.0] + [0.0] * 253, page_number=1),
                DocumentChunk(stored_file_id=1, chunk_index=1, content='Second', embedding=[1.0, 2.0] * 128, slide_number=2, sheet_name='Sheet', cell_range='A1:B2'),
                DocumentChunk(stored_file_id=1, chunk_index=2, content='Third'),
            ])
            session.commit()
            session.expire_all()
            chunks = session.scalars(sa.select(DocumentChunk).order_by(DocumentChunk.chunk_index)).all()
            self.assertEqual(chunks[0].embedding, [0.5, 1.0, -2.0] + [0.0] * 253)
            self.assertEqual(chunks[1].embedding, [1.0, 2.0] * 128)
            self.assertIsNone(chunks[2].embedding)
            self.assertEqual((chunks[1].sheet_name, chunks[1].cell_range), ('Sheet', 'A1:B2'))
            self.assertTrue(all(chunk.id > 0 and chunk.created_at is not None for chunk in chunks))
        native = self.connection.execute(sa.text('''
            SELECT t.typname,a.atttypmod FROM pg_attribute a JOIN pg_type t ON t.oid=a.atttypid
            WHERE a.attrelid='document_chunks'::regclass AND a.attname='embedding'
        ''')).one()
        self.assertEqual(tuple(native), ('vector', 256))
        self.assert_current()

    def test_chunk_constraints_enforced_by_postgresql(self):
        self.prepare()
        self.connection.execute(sa.text("INSERT INTO document_chunks (stored_file_id,chunk_index,content) VALUES (1,0,'Valid')"))
        statements = [
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content) VALUES (1,0,'Duplicate')",
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content) VALUES (1,-1,'Bad')",
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content,page_number) VALUES (1,1,'Bad',0)",
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content,slide_number) VALUES (1,1,'Bad',-1)",
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content) VALUES (999999,1,'Bad')",
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content) VALUES (1,1,NULL)",
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content) VALUES (1,NULL,'Bad')",
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content) VALUES (NULL,1,'Bad')",
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content,sheet_name) VALUES (1,1,'Bad',repeat('x',256))",
            "INSERT INTO document_chunks (stored_file_id,chunk_index,content,cell_range) VALUES (1,1,'Bad',repeat('x',65))",
        ]
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(sa.exc.DBAPIError):
                    with self.connection.begin_nested():
                        self.connection.execute(sa.text(statement))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM document_chunks')), 1)
        self.connection.commit()

    def test_wrong_dimensions_are_rejected_by_postgresql(self):
        self.prepare()
        for size in (1, 255, 257):
            with self.subTest(size=size):
                # Raw SQL bypasses the Python VECTOR adapter's own dimension check.
                with self.assertRaisesRegex(sa.exc.DataError, 'expected 256 dimensions'):
                    with self.connection.begin_nested():
                        self.connection.execute(sa.text(
                            'INSERT INTO document_chunks (stored_file_id,chunk_index,content,embedding) '
                            'VALUES (1,0,\'Artificial\',CAST(:embedding AS vector))'
                        ), {'embedding': str([1.0] * size)})
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM document_chunks')), 0)
        self.connection.commit()

    def prepare_previous_dimension(self, dimensions):
        self.legacy_data()
        command.upgrade(migrations.migration_config(self.connection), '0004_ai_storage')
        for index, size in enumerate(dimensions):
            self.connection.execute(sa.text(
                'INSERT INTO document_chunks (stored_file_id,chunk_index,content,embedding) '
                'VALUES (1,:index,\'Artificial document\',CAST(:embedding AS vector))'
            ), {'index': index, 'embedding': None if size is None else str([0.5] * size)})
        self.connection.execute(sa.text(
            "INSERT INTO ai_retrospectives (launch_id,generated_by_id,content) VALUES (1,1,'Keep AI record')"
        ))
        self.connection.commit()

    def snapshot(self):
        names = sa.inspect(self.connection).get_table_names()
        result = {name: self.connection.execute(sa.text(f'SELECT * FROM "{name}" ORDER BY 1')).all()
                  for name in names if name != 'alembic_version'}
        self.connection.commit()
        return result

    def assert_dimension(self, dimension, revision):
        self.assertEqual(self.connection.scalar(sa.text(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid='document_chunks'::regclass AND attname='embedding'"
        )), dimension)
        self.assertEqual(self.connection.scalar(sa.text('SELECT version_num FROM alembic_version')), revision)
        self.connection.commit()

    def test_dimension_upgrade_repeat_and_downgrade_preserve_all_rows(self):
        self.prepare_previous_dimension([256, None])
        before = self.snapshot()
        self.assert_dimension(-1, '0004_ai_storage')
        self.upgrade()
        self.upgrade()
        self.assertEqual(self.snapshot(), before)
        self.assert_dimension(256, '0005_embedding_dimension')
        self.assert_current()
        self.connection.commit()
        command.downgrade(migrations.migration_config(self.connection), '0004_ai_storage')
        self.assert_dimension(-1, '0004_ai_storage')
        self.assertEqual(self.snapshot(), before)
        self.assertIsNotNone(self.connection.scalar(sa.text("SELECT extversion FROM pg_extension WHERE extname='vector'")))
        self.connection.commit()
        self.upgrade()
        self.assertEqual(self.snapshot(), before)
        self.assert_current()

    def test_incompatible_vectors_roll_back_schema_revision_and_all_rows(self):
        self.prepare_previous_dimension([256, 255, None, 257])
        before = self.snapshot()
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, '2 incompatible rows') as error:
                self.upgrade()
            self.assertNotIn('Artificial document', str(error.exception))
            self.assertNotIn('[0.5', str(error.exception))
            self.assert_dimension(-1, '0004_ai_storage')
            self.assertEqual(self.snapshot(), before)

    def test_dimension_check_blocks_concurrent_writes_until_type_change(self):
        self.prepare_previous_dimension([256])
        blocked = []
        with self.connect() as writer:
            def before_check(connection, cursor, statement, parameters, context, executemany):
                if 'vector_dims(embedding) <> 256' not in statement:
                    return
                try:
                    writer.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
                    with self.assertRaises(sa.exc.OperationalError) as error:
                        writer.execute(sa.text(
                            "INSERT INTO document_chunks (stored_file_id,chunk_index,content,embedding) "
                            "VALUES (1,1,'Concurrent','[1,2]'::vector)"
                        ))
                    self.assertEqual(error.exception.orig.pgcode, '55P03')
                    blocked.append(True)
                finally:
                    writer.rollback()
            sa.event.listen(self.connection, 'before_cursor_execute', before_check)
            try:
                self.upgrade()
            finally:
                sa.event.remove(self.connection, 'before_cursor_execute', before_check)
            self.assertEqual(blocked, [True])
            with self.assertRaisesRegex(sa.exc.DataError, 'expected 256 dimensions'):
                writer.execute(sa.text(
                    "INSERT INTO document_chunks (stored_file_id,chunk_index,content,embedding) "
                    "VALUES (1,1,'Concurrent','[1,2]'::vector)"
                ))
            writer.rollback()
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM document_chunks')), 1)
        self.assert_current()

    def test_one_chunk_set_is_shared_and_removed_only_with_physical_file(self):
        self.prepare()
        self.connection.execute(sa.text("INSERT INTO launches (module_id,title,description,year,semester) VALUES (1,'Second','',2028,'Spring')"))
        self.connection.execute(sa.text("INSERT INTO materials (launch_id,stored_file_id,title) VALUES (2,1,'Shared')"))
        self.connection.execute(sa.text("INSERT INTO document_chunks (stored_file_id,chunk_index,content) VALUES (1,0,'Shared text')"))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM materials WHERE stored_file_id=1')), 2)
        self.connection.execute(sa.text('DELETE FROM launches WHERE id=1'))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM document_chunks')), 1)
        with self.assertRaises(sa.exc.IntegrityError):
            with self.connection.begin_nested():
                self.connection.execute(sa.text('DELETE FROM stored_files WHERE id=1'))
        self.connection.execute(sa.text('DELETE FROM launches WHERE id=2'))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM document_chunks')), 1)
        self.connection.execute(sa.text('DELETE FROM stored_files WHERE id=1'))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM document_chunks')), 0)
        self.connection.commit()

    def test_retrospective_constraints_indexes_and_delete_rules(self):
        self.prepare()
        self.connection.execute(sa.text("INSERT INTO users (username,email,hashed_password) VALUES ('generator','generator@example.com','test')"))
        self.connection.execute(sa.text("INSERT INTO launches (module_id,title,year,semester) VALUES (1,'Comparison',2028,'Spring')"))
        self.connection.commit()
        with Session(bind=self.connection) as session:
            item = AIRetrospective(launch_id=1, compared_to_launch_id=2, generated_by_id=2, content='Artificial test result')
            session.add(item)
            session.commit()
            session.refresh(item)
            self.assertGreater(item.id, 0)
            self.assertIsNotNone(item.created_at)
            self.assertEqual(item.content, 'Artificial test result')
        statements = [
            "INSERT INTO ai_retrospectives (launch_id,compared_to_launch_id,generated_by_id,content) VALUES (1,1,2,'Bad')",
            "INSERT INTO ai_retrospectives (launch_id,generated_by_id,content) VALUES (999999,2,'Bad')",
            "INSERT INTO ai_retrospectives (launch_id,compared_to_launch_id,generated_by_id,content) VALUES (1,999999,2,'Bad')",
            "INSERT INTO ai_retrospectives (launch_id,generated_by_id,content) VALUES (1,999999,'Bad')",
            "INSERT INTO ai_retrospectives (launch_id,generated_by_id,content) VALUES (NULL,2,'Bad')",
            "INSERT INTO ai_retrospectives (launch_id,generated_by_id,content) VALUES (1,NULL,'Bad')",
            "INSERT INTO ai_retrospectives (launch_id,generated_by_id,content) VALUES (1,2,NULL)",
            "DELETE FROM users WHERE id=2",
        ]
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(sa.exc.IntegrityError):
                    with self.connection.begin_nested():
                        self.connection.execute(sa.text(statement))
        inspector = sa.inspect(self.connection)
        indexes = inspector.get_indexes('ai_retrospectives')
        self.assertEqual({tuple(index['column_names']) for index in indexes},
                         {('launch_id', 'created_at'), ('compared_to_launch_id',), ('generated_by_id',)})
        self.assertTrue(all(not index['unique'] for index in indexes))
        self.assertEqual(inspector.get_unique_constraints('document_chunks')[0]['column_names'], ['stored_file_id', 'chunk_index'])
        self.assertFalse(any(index.get('dialect_options', {}).get('postgresql_using') in ('hnsw', 'ivfflat')
                             for index in inspector.get_indexes('document_chunks')))
        self.connection.execute(sa.text('DELETE FROM launches WHERE id=2'))
        self.assertIsNone(self.connection.scalar(sa.text('SELECT compared_to_launch_id FROM ai_retrospectives')))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM ai_retrospectives')), 1)
        self.connection.execute(sa.text('DELETE FROM launches WHERE id=1'))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM ai_retrospectives')), 0)
        self.connection.execute(sa.text('DELETE FROM users WHERE id=2'))
        self.connection.commit()
        self.assert_current()

    def test_copy_does_not_duplicate_chunks_ai_results_or_manual_reflection(self):
        self.prepare()
        self.connection.execute(sa.text("INSERT INTO document_chunks (stored_file_id,chunk_index,content) VALUES (1,0,'Shared')"))
        self.connection.execute(sa.text("INSERT INTO ai_retrospectives (launch_id,generated_by_id,content) VALUES (1,1,'Keep AI record')"))
        self.connection.execute(sa.text("INSERT INTO launch_reflections (launch_id,what_went_well) VALUES (1,'Keep manual reflection')"))
        self.connection.commit()
        from repositories.launches import LaunchRepository
        from services.launches import LaunchService
        from schemas.launches import CreateLaunchRequest
        with Session(bind=self.connection) as session:
            copied = LaunchService(repository=LaunchRepository(session)).copy_launch(
                1, 1, CreateLaunchRequest(title='Copy', year=2029, semester='Spring'))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM document_chunks')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM ai_retrospectives')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SELECT launch_id FROM ai_retrospectives')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SELECT what_went_well FROM launch_reflections WHERE launch_id=1')), 'Keep manual reflection')
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM launch_reflections WHERE launch_id=:id'), {'id': copied['id']}), 0)
        self.assertEqual(self.connection.scalar(sa.text('SELECT stored_file_id FROM materials WHERE launch_id=:id'), {'id': copied['id']}), 1)
        self.connection.commit()

    def test_downgrade_keeps_extension_and_other_schema_objects(self):
        self.prepare()
        self.connection.execute(sa.text('CREATE TABLE public.kms_vector_keep (embedding public.vector)'))
        self.connection.commit()
        try:
            command.downgrade(migrations.migration_config(self.connection), '0003_notes_reflections')
            self.assertIsNotNone(self.connection.scalar(sa.text("SELECT extversion FROM pg_extension WHERE extname='vector'")))
            self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM notes')), 1)
            self.assertNotIn('document_chunks', sa.inspect(self.connection).get_table_names())
            self.assertNotIn('ai_retrospectives', sa.inspect(self.connection).get_table_names())
            self.connection.commit()
            self.upgrade()
            self.assert_current()
        finally:
            self.connection.rollback()
            self.connection.execute(sa.text('DROP TABLE public.kms_vector_keep'))
            self.connection.commit()

    def test_extension_lives_outside_isolated_schema(self):
        self.legacy_data()
        self.connection.execute(sa.text(f'SET search_path TO "{self.schema}"'))
        self.connection.commit()
        self.upgrade()
        schema = self.connection.scalar(sa.text("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'"))
        self.assertEqual(schema, 'public')
        self.assertEqual(self.connection.scalar(sa.text('SELECT current_schema()')), self.schema)
        self.connection.commit()
        self.assert_current()
