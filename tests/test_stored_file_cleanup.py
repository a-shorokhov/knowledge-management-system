import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

import test_erd as runtime
from core.exceptions import FileCleanupFailedException
from models.launches import Launch
from models.materials import Material
from models.modules import Module
from models.sections import RunSection
from models.stored_files import StoredFile
from models.users import User
from repositories.materials import MaterialRepository
from repositories.stored_files import StoredFileRepository
from services.stored_files import StoredFileService


class CleanupAttemptTests(unittest.TestCase):
    setUp = runtime.ERDTests.setUp
    tearDown = runtime.ERDTests.tearDown
    material = runtime.ERDTests.material
    request = runtime.ERDTests.request
    run_data = staticmethod(runtime.ERDTests.run_data)

    def test_each_attempt_releases_read_transactions_including_skipped_files(self):
        material = self.material()
        service = StoredFileService(self.files, self.materials, self.storage)
        original = self.files.get_file_by_id
        starts = []

        def observe(file_id, user_id):
            starts.append(self.db.in_transaction())
            return original(file_id, user_id)

        self.db.rollback()
        with patch.object(self.files, 'get_file_by_id', side_effect=observe):
            service.delete_unused_files([material['stored_file_id'], 99999], 1)
        self.assertEqual(starts, [False, False])
        self.assertFalse(self.db.in_transaction())
        self.assertEqual(len(self.storage.objects), 1)

    def test_rollback_failure_is_reported_and_later_attempt_can_recover(self):
        service = StoredFileService(self.files, self.materials, self.storage)
        rollback = self.db.rollback
        attempts = []

        def flaky_rollback():
            attempts.append(True)
            if len(attempts) == 1:
                raise sa.exc.SQLAlchemyError('Temporary rollback failure')
            rollback()

        with patch.object(self.db, 'rollback', side_effect=flaky_rollback):
            with self.assertRaises(FileCleanupFailedException) as error:
                service.delete_unused_files([99998, 99999], 1)
        self.assertEqual(error.exception.detail['ErrorContext'], {'file_ids': [99998]})
        self.assertEqual(len(attempts), 2)
        self.assertFalse(self.db.in_transaction())


@unittest.skipUnless(
    os.environ.get('KMS_TEST_CLEANUP_DATABASE_URL') or os.environ.get('KMS_TEST_DATABASE_URL'),
    'Нужен отдельный PostgreSQL: KMS_TEST_CLEANUP_DATABASE_URL или KMS_TEST_DATABASE_URL',
)
class CleanupPostgreSQLTests(unittest.TestCase):
    request = runtime.ERDTests.request

    def setUp(self):
        url = os.environ.get('KMS_TEST_CLEANUP_DATABASE_URL') or os.environ['KMS_TEST_DATABASE_URL']
        self.engine = sa.create_engine(url, hide_parameters=True)
        self.schema = 'kms_cleanup_test_' + uuid4().hex
        self.connection = self.engine.connect()
        self.connection.execute(sa.schema.CreateSchema(self.schema))
        self.connection.execute(sa.text(f'SET search_path TO "{self.schema}"'))
        # Exercise the production cleanup tables on PostgreSQL itself. The two
        # AI tables are unrelated to cleanup; their vector tests run separately.
        tables = [table for table in runtime.database.Base.metadata.sorted_tables
                  if table.name not in {'document_chunks', 'ai_retrospectives'}]
        runtime.database.Base.metadata.create_all(self.connection, tables=tables)
        self.connection.commit()
        self.db = Session(bind=self.connection)
        self.db.add(User(id=1, username='cleanup', email='cleanup@example.com', hashed_password='unused'))
        self.db.flush()
        self.db.add_all([
            Module(id=1, owner_id=1, title='Delete', description=''),
            Module(id=2, owner_id=1, title='Keep', description=''),
        ])
        self.db.flush()
        self.db.add_all([
            Launch(id=1, module_id=1, title='Delete', year=2026, semester='Autumn'),
            Launch(id=2, module_id=2, title='Keep', year=2026, semester='Autumn'),
        ])
        self.db.flush()
        self.db.add(RunSection(id=1, launch_id=1, title='Delete section'))
        self.db.flush()
        self.storage = runtime.FakeStorage()
        for file_id in (1, 2, 3):
            key = f'cleanup/{file_id}.txt'
            self.db.add(StoredFile(
                id=file_id, bucket=runtime.config.settings.S3_BUCKET, storage_key=key,
                original_filename=f'{file_id}.txt', mime_type='text/plain', size_bytes=1, uploaded_by_id=1,
            ))
            self.storage.upload_file(key, b'a')
        self.db.flush()
        self.db.add_all([
            Material(id=i, launch_id=1, section_id=1, stored_file_id=i, title=f'File {i}') for i in (1, 2, 3)
        ] + [Material(id=4, launch_id=2, stored_file_id=3, title='Shared file')])
        self.db.commit()
        self.files = StoredFileRepository(self.db)
        self.materials = MaterialRepository(self.db)
        runtime.app.dependency_overrides[runtime.database.get_db] = lambda: self.db
        runtime.app.dependency_overrides[runtime.get_current_user] = lambda: {'id': 1}
        runtime.app.dependency_overrides[runtime.get_file_storage] = lambda: self.storage
        runtime.app.dependency_overrides[StoredFileRepository] = lambda: self.files

    def tearDown(self):
        runtime.app.dependency_overrides.clear()
        self.db.close()
        self.connection.rollback()
        self.connection.execute(sa.schema.DropSchema(self.schema, cascade=True))
        self.connection.commit()
        self.connection.close()
        self.engine.dispose()

    def assert_failed_transaction_recovers(self, operation, path, parent_table):
        from psycopg2.extensions import TRANSACTION_STATUS_IDLE, TRANSACTION_STATUS_INERROR

        original = getattr(self.files, operation)
        failed_states = []
        next_states = []
        driver = self.connection.connection.driver_connection

        def fail_first(file_id, *args):
            if file_id == 1 and not failed_states:
                try:
                    self.db.execute(sa.text('SELECT 1 / 0'))
                except sa.exc.DBAPIError as error:
                    self.assertEqual(error.orig.pgcode, '22012')
                    failed_states.append(driver.get_transaction_status())
                    self.assertEqual(failed_states, [TRANSACTION_STATUS_INERROR])
                    raise
            if file_id == 2 and not next_states:
                next_states.append(driver.get_transaction_status())
                # For the preliminary read the previous attempt must be fully
                # rolled back before this file starts its own transaction.
                if operation == 'get_file_by_id':
                    self.assertFalse(self.db.in_transaction())
                    self.assertEqual(driver.get_transaction_status(), TRANSACTION_STATUS_IDLE)
                else:
                    self.assertNotEqual(driver.get_transaction_status(), TRANSACTION_STATUS_INERROR)
            return original(file_id, *args)

        with patch.object(self.files, operation, side_effect=fail_first):
            status, response = self.request('DELETE', path)
        self.assertEqual(status, 503)
        self.assertEqual(response['error']['ErrorCode'], 'FILE_CLEANUP_FAILED')
        self.assertEqual(response['error']['ErrorContext'], {'file_ids': [1]})
        self.assertIn('и его содержимое удалены', response['error']['ErrorMessage'])
        self.assertEqual(failed_states, [TRANSACTION_STATUS_INERROR])
        self.assertTrue(next_states)
        self.assertFalse(self.db.in_transaction())
        # Check committed results independently of the request session.
        with self.engine.connect() as observer:
            self.assertEqual(observer.scalar(sa.text(f'SELECT count(*) FROM "{self.schema}".{parent_table} WHERE id=1')), 0)
            rows = observer.execute(sa.text(
                f'SELECT id,deletion_pending FROM "{self.schema}".stored_files ORDER BY id'
            )).all()
            self.assertEqual(rows, [(1, True), (3, False)])
            self.assertEqual(observer.scalar(sa.text(
                f'SELECT stored_file_id FROM "{self.schema}".materials WHERE id=4'
            )), 3)
        if operation == 'delete_file':
            self.assertNotIn('cleanup/1.txt', self.storage.objects)
        else:
            self.assertIn('cleanup/1.txt', self.storage.objects)
        self.assertNotIn('cleanup/2.txt', self.storage.objects)
        self.assertIn('cleanup/3.txt', self.storage.objects)
        self.assertEqual(self.request('DELETE', '/stored-files/1')[0], 200)
        service = StoredFileService(self.files, self.materials, self.storage)
        self.assertTrue(service.delete_unused_files([1, 1, 3], 1)['success'])
        self.assertFalse(self.db.in_transaction())
        self.assertIsNone(self.db.get(StoredFile, 1))
        self.assertFalse(self.db.get(StoredFile, 3).deletion_pending)
        self.assertEqual(set(self.storage.objects), {'cleanup/3.txt'})

    def test_lookup_sql_failure_recovers_before_next_file(self):
        self.assert_failed_transaction_recovers('get_file_by_id', '/launches/1', 'launches')

    def test_usage_sql_failure_after_module_deletion_recovers(self):
        self.assert_failed_transaction_recovers('is_file_used', '/modules/1', 'modules')

    def test_record_deletion_sql_failure_keeps_pending_intent_and_recovers(self):
        self.assert_failed_transaction_recovers('delete_file', '/launches/1', 'launches')

    def test_lookup_sql_failure_after_section_deletion_recovers(self):
        self.assert_failed_transaction_recovers('get_file_by_id', '/sections/1', 'run_sections')
