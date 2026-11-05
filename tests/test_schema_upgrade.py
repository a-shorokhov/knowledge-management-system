"""Миграции проверяются отдельно от пользовательской БД и S3."""
import importlib.util
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_erd as test_runtime
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]


def migration_config(connection=None):
    config = Config(str(ROOT / 'alembic.ini'))
    if connection is not None:
        config.attributes['connection'] = connection
    return config


class MigrationConfigurationTests(unittest.TestCase):
    def test_revision_chain_preserves_initial_schema(self):
        scripts = ScriptDirectory.from_config(migration_config())
        self.assertEqual(scripts.get_heads(), ['0005_embedding_dimension'])
        self.assertEqual([revision.revision for revision in scripts.walk_revisions()], ['0005_embedding_dimension', '0004_ai_storage', '0003_notes_reflections', '0002_launch_designs', '0001_initial'])
        initial = scripts.get_revision('0001_initial').module._schema()
        actual = test_runtime.database.Base.metadata
        self.assertEqual(set(actual.tables), set(initial.tables) | {'launch_designs', 'launch_reflections', 'document_chunks', 'ai_retrospectives'})
        added_columns = {'starts_on', 'ends_on', 'participant_count', 'changes_summary', 'changes_reason'}
        for name, table in initial.tables.items():
            expected = set(table.columns.keys()) | (added_columns if name == 'launches' else {'problem_or_practice', 'cause', 'proposed_solution', 'priority', 'status'} if name == 'notes' else set())
            self.assertEqual(set(actual.tables[name].columns.keys()), expected)

    def test_start_runs_migrations_before_server_and_stops_on_failure(self):
        spec = importlib.util.spec_from_file_location('kms_start', ROOT / 'app' / 'start.py')
        start = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(start)
        events = []
        with patch.object(start.command, 'upgrade', side_effect=lambda *args: events.append('migration')), patch.object(start.os, 'execv', side_effect=lambda *args: events.append('server')):
            start.main()
        self.assertEqual(events, ['migration', 'server'])
        with patch.object(start.command, 'upgrade', side_effect=RuntimeError('migration failed')), patch.object(start.os, 'execv') as server:
            with self.assertRaises(RuntimeError):
                start.main()
            server.assert_not_called()


@unittest.skipUnless(os.environ.get('KMS_TEST_DATABASE_URL'), 'Для интеграционных проверок нужен отдельный PostgreSQL: KMS_TEST_DATABASE_URL')
class PostgreSQLMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine(os.environ['KMS_TEST_DATABASE_URL'], hide_parameters=True)
        self.schema = 'kms_migration_test_' + uuid4().hex
        with self.engine.begin() as connection:
            connection.execute(sa.schema.CreateSchema(self.schema))
        self.connection = self.connect()

    def connect(self):
        connection = self.engine.connect()
        connection.execute(sa.text(f'SET search_path TO "{self.schema}", public'))
        connection.commit()
        return connection

    def tearDown(self):
        self.connection.close()
        with self.engine.begin() as connection:
            connection.execute(sa.schema.DropSchema(self.schema, cascade=True))
        self.engine.dispose()

    def upgrade(self):
        self.connection.commit()
        command.upgrade(migration_config(self.connection), 'head')

    def assert_current(self):
        self.connection.commit()
        command.check(migration_config(self.connection))
        self.assertEqual(self.connection.scalar(sa.text('SELECT version_num FROM alembic_version')), '0005_embedding_dimension')

    def legacy_data(self):
        statements = [
            "CREATE TABLE users (id SERIAL PRIMARY KEY, username VARCHAR(32) NOT NULL, email VARCHAR NOT NULL, hashed_password VARCHAR NOT NULL, CONSTRAINT uq_users_username UNIQUE(username), CONSTRAINT uq_users_email UNIQUE(email))",
            "CREATE TABLE modules (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, title VARCHAR(255) NOT NULL, description TEXT)",
            "CREATE TABLE launches (id SERIAL PRIMARY KEY, module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE, year INTEGER NOT NULL, title VARCHAR(255), description TEXT)",
            "CREATE TABLE materials (id SERIAL PRIMARY KEY, launch_id INTEGER NOT NULL REFERENCES launches(id) ON DELETE CASCADE, title VARCHAR(255) NOT NULL, description TEXT, original_filename VARCHAR(255) NOT NULL, storage_key TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
            "CREATE TABLE notes (id SERIAL PRIMARY KEY, launch_id INTEGER NOT NULL REFERENCES launches(id) ON DELETE CASCADE, title VARCHAR(255) NOT NULL, content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
            "CREATE TABLE templates (id SERIAL PRIMARY KEY, title TEXT)",
            "INSERT INTO users (username,email,hashed_password) VALUES ('old_user','old@example.com','original-hash')",
            "INSERT INTO modules (user_id,title) VALUES (1,'Existing module')",
            "INSERT INTO launches (module_id,year) VALUES (1,2025)",
            "INSERT INTO materials (launch_id,title,original_filename,storage_key) VALUES (1,'Lecture','lecture.txt','materials/keep/lecture.txt')",
            "INSERT INTO notes (launch_id,title,content) VALUES (1,'Note','Do not lose this text')",
            "INSERT INTO templates (title) VALUES ('Leave this table alone')",
        ]
        for statement in statements:
            self.connection.execute(sa.text(statement))
        self.connection.commit()

    def test_empty_database_repeat_upgrade_and_no_model_drift(self):
        self.upgrade()
        self.upgrade()
        self.assert_current()
        self.assertEqual(set(sa.inspect(self.connection).get_table_names()), set(test_runtime.database.Base.metadata.tables) | {'alembic_version'})

    def test_legacy_data_and_storage_keys_survive(self):
        self.legacy_data()
        self.upgrade()
        self.assert_current()
        self.assertEqual(self.connection.scalar(sa.text('SELECT hashed_password FROM users WHERE id=1')), 'original-hash')
        self.assertEqual(self.connection.scalar(sa.text('SELECT owner_id FROM modules WHERE id=1')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SELECT author_id FROM notes WHERE id=1')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SELECT content FROM notes WHERE id=1')), 'Do not lose this text')
        stored = self.connection.execute(sa.text('SELECT storage_key,mime_type,size_bytes FROM stored_files')).one()
        self.assertEqual(tuple(stored), ('materials/keep/lecture.txt', 'text/plain', 0))
        self.assertEqual(self.connection.scalar(sa.text('SELECT stored_file_id FROM materials WHERE id=1')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SELECT title FROM templates')), 'Leave this table alone')
        self.connection.commit()
        self.upgrade()
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM stored_files')), 1)

    def test_design_migration_backfills_existing_launches_without_changing_data(self):
        self.legacy_data()
        command.upgrade(migration_config(self.connection), '0001_initial')
        before = self.connection.execute(sa.text('SELECT id,title,description,year,semester,status,created_at,updated_at FROM launches')).all()
        self.connection.commit()
        self.upgrade()
        after = self.connection.execute(sa.text('SELECT id,title,description,year,semester,status,created_at,updated_at FROM launches')).all()
        self.assertEqual(before, after)
        design = self.connection.execute(sa.text('SELECT launch_id,template_version,data,created_at,updated_at FROM launch_designs')).one()
        self.assertEqual(tuple(design[:3]), (1, 1, {}))
        self.assertIsNotNone(design.created_at)
        self.assertIsNotNone(design.updated_at)
        self.assertEqual(self.connection.scalar(sa.text('SELECT participant_count FROM launches WHERE id=1')), None)
        self.assert_current()
        self.upgrade()
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM launch_designs')), 1)

    def test_design_jsonb_constraints_and_cascade(self):
        self.legacy_data()
        self.upgrade()
        columns = {column['name']: column for column in sa.inspect(self.connection).get_columns('launch_designs')}
        self.assertIsInstance(columns['data']['type'], sa.dialects.postgresql.JSONB)
        invalid_updates = [
            "UPDATE launch_designs SET data='[]'::jsonb",
            "UPDATE launch_designs SET data='null'::jsonb",
            "UPDATE launch_designs SET template_version=0",
            "UPDATE launches SET participant_count=-1",
            "UPDATE launches SET starts_on='2027-05-01', ends_on='2027-02-01'",
        ]
        for statement in invalid_updates:
            with self.subTest(statement=statement):
                with self.assertRaises(sa.exc.IntegrityError):
                    with self.connection.begin_nested():
                        self.connection.execute(sa.text(statement))
        self.connection.execute(sa.text('DELETE FROM launches WHERE id=1'))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM launch_designs')), 0)
        self.connection.commit()

    def test_postgresql_design_repository_roundtrip(self):
        self.legacy_data()
        self.upgrade()
        from sqlalchemy.orm import Session
        from repositories.launch_designs import LaunchDesignRepository
        from repositories.launches import LaunchRepository
        data = {'educational_concept': {'learning_outcomes': ['Third', 'First', 'Second']},
                'project': {'stages': [{'position': 5}, {'position': 1}]}}
        with Session(bind=self.connection) as session:
            launch = LaunchRepository(session).create_launch(1, {'title': 'New', 'year': 2027, 'semester': 'Spring'})
            repository = LaunchDesignRepository(session)
            self.assertEqual(repository.get_design(launch['id'], 1)['data'], {})
            repository.replace_design(launch['id'], 1, 1, data)
            session.expire_all()
            self.assertEqual(repository.get_design(launch['id'], 1)['data'], data)
            repository.replace_design(launch['id'], 1, 1, {})
            self.assertEqual(repository.get_design(launch['id'], 1)['data'], {})
        self.assert_current()

    def test_postgresql_launch_copy_preserves_design_and_shared_file_links(self):
        self.legacy_data()
        self.upgrade()
        self.connection.execute(sa.text("INSERT INTO run_sections (launch_id,title,position) VALUES (1,'Teaching',0),(1,'Empty',1)"))
        self.connection.execute(sa.text("UPDATE materials SET section_id=(SELECT id FROM run_sections WHERE title='Teaching') WHERE id=1"))
        self.connection.execute(sa.text("INSERT INTO materials (launch_id,stored_file_id,title,kind) SELECT 1,stored_file_id,'Feedback','feedback' FROM materials WHERE id=1"))
        self.connection.commit()
        from sqlalchemy.orm import Session
        from repositories.launch_designs import LaunchDesignRepository
        from repositories.launches import LaunchRepository
        from services.launches import LaunchService
        from schemas.launches import CreateLaunchRequest
        data = {'project': {'stages': [{'position': 2}, {'position': 0}]}}
        with Session(bind=self.connection) as session:
            designs = LaunchDesignRepository(session)
            designs.replace_design(1, 1, 1, data)
            copied = LaunchService(repository=LaunchRepository(session)).copy_launch(
                1, 1, CreateLaunchRequest(title='Copy', year=2028, semester='Spring'),
            )
            self.assertEqual(designs.get_design(copied['id'], 1)['data'], data)
            designs.replace_design(copied['id'], 1, 1, {})
            self.assertEqual(designs.get_design(1, 1)['data'], data)
            launch_id = copied['id']
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM run_sections WHERE launch_id=:id'), {'id': launch_id}), 2)
        rows = self.connection.execute(sa.text('SELECT stored_file_id,copied_from_material_id,section_id FROM materials WHERE launch_id=:id'), {'id': launch_id}).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(tuple(rows[0][:2]), (1, 1))
        self.assertEqual(self.connection.scalar(sa.text('SELECT launch_id FROM run_sections WHERE id=:id'), {'id': rows[0].section_id}), launch_id)
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM notes WHERE launch_id=:id'), {'id': launch_id}), 0)
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM stored_files')), 1)
        self.assert_current()

    def test_notes_migration_preserves_existing_text_links_and_timestamps(self):
        self.legacy_data()
        command.upgrade(migration_config(self.connection), '0002_launch_designs')
        before = self.connection.execute(sa.text('SELECT id,launch_id,material_id,section_id,author_id,title,content,created_at,updated_at FROM notes')).all()
        self.connection.commit()
        self.upgrade()
        after = self.connection.execute(sa.text('SELECT id,launch_id,material_id,section_id,author_id,title,content,created_at,updated_at FROM notes')).all()
        self.assertEqual(before, after)
        values = self.connection.execute(sa.text('SELECT problem_or_practice,cause,proposed_solution,priority,status FROM notes')).one()
        self.assertEqual(tuple(values), (None, None, None, 'medium', 'open'))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM launch_reflections')), 0)
        self.connection.execute(sa.text("UPDATE notes SET cause='Keep cause',priority='high',status='done' WHERE id=1"))
        self.connection.commit()
        self.upgrade()
        self.assertEqual(tuple(self.connection.execute(sa.text('SELECT cause,priority,status FROM notes WHERE id=1')).one()), ('Keep cause', 'high', 'done'))
        self.assert_current()

    def test_postgresql_reflection_replacement_constraints_and_cascade(self):
        self.legacy_data()
        self.upgrade()
        from sqlalchemy.orm import Session
        from repositories.launch_reflections import LaunchReflectionRepository
        from schemas.launch_reflections import ReplaceLaunchReflectionRequest
        with Session(bind=self.connection) as session:
            repository = LaunchReflectionRepository(session)
            self.assertIsNone(repository.get_reflection(1, 1)['created_at'])
            fields = ReplaceLaunchReflectionRequest(what_went_well='Good', decisions_to_keep='Keep').model_dump()
            first = repository.replace_reflection(1, 1, fields)
            second = repository.replace_reflection(1, 1, ReplaceLaunchReflectionRequest(recurring_problems='Problem').model_dump())
            self.assertEqual(second['created_at'], first['created_at'])
            self.assertIsNone(second['what_went_well'])
            self.assertIsNone(second['decisions_to_keep'])
            self.assertEqual(repository.get_reflection(1, 1)['recurring_problems'], 'Problem')
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM launch_reflections')), 1)
        for statement in [
            "UPDATE notes SET priority='urgent'",
            "UPDATE notes SET status='closed'",
            "UPDATE notes SET priority=NULL",
            "UPDATE notes SET status=NULL",
            "INSERT INTO launch_reflections (launch_id) VALUES (1)",
            "INSERT INTO launch_reflections (launch_id) VALUES (999999)",
        ]:
            with self.subTest(statement=statement):
                with self.assertRaises(sa.exc.DBAPIError):
                    with self.connection.begin_nested():
                        self.connection.execute(sa.text(statement))
        self.connection.execute(sa.text('DELETE FROM launches WHERE id=1'))
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM launch_reflections')), 0)
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM notes')), 0)
        self.connection.commit()
        self.assert_current()

    def test_concurrent_reflection_puts_create_one_record(self):
        self.legacy_data()
        self.upgrade()
        self.connection.commit()
        code = f"""
import sys, os
sys.path.insert(0, {str(ROOT / 'tests')!r})
import test_erd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from repositories.launch_reflections import LaunchReflectionRepository
engine = create_engine(os.environ['KMS_TEST_DATABASE_URL'], hide_parameters=True)
with engine.connect() as connection:
    connection.execute(text('SET search_path TO "{self.schema}", public'))
    connection.commit()
    with Session(bind=connection) as session:
        LaunchReflectionRepository(session).replace_reflection(1, 1, {{
            'what_went_well': sys.argv[1], 'recurring_problems': None,
            'materials_to_update': None, 'decisions_to_keep': None,
        }})
engine.dispose()
"""
        processes = [subprocess.Popen([sys.executable, '-B', '-c', code, value], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for value in ('First', 'Second')]
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, stderr)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM launch_reflections WHERE launch_id=1')), 1)
        self.assertIn(self.connection.scalar(sa.text('SELECT what_went_well FROM launch_reflections WHERE launch_id=1')), ('First', 'Second'))
        self.assert_current()

    def test_existing_erd_gets_missing_columns_and_cascades(self):
        ScriptDirectory.from_config(migration_config()).get_revision('0001_initial').module._schema().create_all(self.connection)
        self.connection.execute(sa.text('ALTER TABLE notes DROP COLUMN section_id CASCADE'))
        self.connection.execute(sa.text('ALTER TABLE stored_files DROP COLUMN deletion_pending'))
        self.connection.execute(sa.text('ALTER TABLE launches DROP CONSTRAINT fk_launch_module'))
        self.connection.execute(sa.text('ALTER TABLE launches ADD CONSTRAINT old_module_fk FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE RESTRICT'))
        self.connection.commit()
        self.upgrade()
        self.assert_current()

    def test_bad_data_rolls_back_entire_upgrade(self):
        self.legacy_data()
        self.connection.execute(sa.text('UPDATE launches SET year=0'))
        self.connection.commit()
        with self.assertRaises(sa.exc.IntegrityError):
            self.upgrade()
        columns = {item['name'] for item in sa.inspect(self.connection).get_columns('modules')}
        self.assertIn('user_id', columns)
        self.assertNotIn('owner_id', columns)
        self.assertEqual(self.connection.scalar(sa.text('SELECT storage_key FROM materials')), 'materials/keep/lecture.txt')
        self.assertNotIn('stored_files', sa.inspect(self.connection).get_table_names())
        self.assertNotIn('alembic_version', sa.inspect(self.connection).get_table_names())

    def test_conflicting_legacy_file_ownership_is_not_guessed(self):
        self.legacy_data()
        self.connection.execute(sa.text("INSERT INTO users (username,email,hashed_password) VALUES ('other','other@example.com','hash')"))
        self.connection.execute(sa.text("INSERT INTO modules (user_id,title) VALUES (2,'Other module')"))
        self.connection.execute(sa.text("INSERT INTO launches (module_id,year) VALUES (2,2026)"))
        self.connection.execute(sa.text("INSERT INTO materials (launch_id,title,original_filename,storage_key) VALUES (2,'Shared','lecture.txt','materials/keep/lecture.txt')"))
        self.connection.commit()
        with self.assertRaisesRegex(RuntimeError, 'разные владельцы'):
            self.upgrade()
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM materials')), 2)
        self.assertIn('user_id', {item['name'] for item in sa.inspect(self.connection).get_columns('modules')})
        self.assertNotIn('stored_files', sa.inspect(self.connection).get_table_names())

    def test_partial_unknown_schema_is_preserved(self):
        self.connection.execute(sa.text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
        self.connection.commit()
        with self.assertRaisesRegex(RuntimeError, 'неполная схема'):
            self.upgrade()
        self.assertEqual(sa.inspect(self.connection).get_table_names(), ['users'])

    def test_concurrent_startups_apply_initial_revision_once(self):
        code = f"""
import sys
sys.path.insert(0, {str(ROOT / 'tests')!r})
import test_erd
import os
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
engine = create_engine(os.environ['KMS_TEST_DATABASE_URL'], hide_parameters=True)
with engine.connect() as connection:
    connection.execute(text('SET search_path TO "{self.schema}", public'))
    connection.commit()
    config = Config({str(ROOT / 'alembic.ini')!r})
    config.attributes['connection'] = connection
    command.upgrade(config, 'head')
engine.dispose()
"""
        processes = [subprocess.Popen([sys.executable, '-B', '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, stderr)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assert_current()

    def test_future_revision_keeps_existing_rows_and_runs_once(self):
        self.upgrade()
        self.connection.execute(sa.text("INSERT INTO users (username,email,hashed_password) VALUES ('kept','kept@example.com','kept-hash')"))
        self.connection.commit()
        with TemporaryDirectory() as directory:
            scripts = Path(directory) / 'alembic'
            shutil.copytree(ROOT / 'alembic', scripts)
            config = migration_config(self.connection)
            config.set_main_option('script_location', str(scripts))
            revision = command.revision(config, message='Добавить необязательное поле', rev_id='0006_test')
            path = Path(revision.path)
            path.write_text(path.read_text().replace('def upgrade():\n    pass', "def upgrade():\n    op.add_column('users', sa.Column('nickname', sa.String(50), nullable=True))"))
            command.upgrade(config, 'head')
            command.upgrade(config, 'head')
        user = self.connection.execute(sa.text('SELECT username,hashed_password,nickname FROM users')).one()
        self.assertEqual(tuple(user), ('kept', 'kept-hash', None))
        self.assertEqual(self.connection.scalar(sa.text('SELECT version_num FROM alembic_version')), '0006_test')
