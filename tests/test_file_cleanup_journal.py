import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Event
import time
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import sqlalchemy as sa
from sqlalchemy.orm import Session

import test_erd as runtime
import test_stored_file_cleanup as cleanup_tests
from adapters.file_cleanup_journal import CleanupJob, FileCleanupJournal, JournalError
from adapters.file_storage.base import FileStorageError
from core.depends import get_file_cleanup_journal
from core.exceptions import FileJournalUnavailableException, FileUploadFailedException, MaterialSaveFailedException, MaterialFileReplacementFailedException
from models.materials import Material
from models.stored_files import StoredFile
from models.users import User
from repositories.stored_files import StoredFileRepository
from services.file_cleanup import FileCleanupService


class JournalPersistenceTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='kms-journal-')
        self.addCleanup(directory.cleanup)
        self.directory = directory.name
        self.journal = FileCleanupJournal(self.directory)

    def test_intent_is_synced_before_yield_and_reopened_after_process_exit(self):
        code = '''
import os, sys
from adapters.file_cleanup_journal import FileCleanupJournal
with FileCleanupJournal(sys.argv[1]).create('bucket', 'key') as job:
    job.update(state='uploaded')
    print(job.data['id'], flush=True)
    os._exit(0)
'''
        result = self.process(code)
        job_id = result.stdout.strip()
        with FileCleanupJournal(self.directory).claim(job_id) as job:
            self.assertEqual(job.data['state'], 'uploaded')
            self.assertEqual(job.data['bucket'], 'bucket')
            self.assertEqual(job.data['storage_key'], 'key')
            self.assertEqual(job.data['attempts'], 0)

    def process(self, code, *args):
        return subprocess.run(
            [sys.executable, '-B', '-c', code, self.directory, *args],
            env={**os.environ, 'PYTHONPATH': str(runtime.APP)}, capture_output=True,
            text=True, check=True, timeout=20,
        )

    def test_multiple_processes_serialize_atomic_updates_and_skip_active_job(self):
        with self.journal.create('bucket', 'key') as job:
            job_id = job.data['id']
            result = self.process('''
import sys
from adapters.file_cleanup_journal import FileCleanupJournal
with FileCleanupJournal(sys.argv[1]).claim(sys.argv[2]) as job:
    print('busy' if job is None else 'claimed')
''', job_id)
            self.assertEqual(result.stdout.strip(), 'busy')
        code = '''
import sys, time
from adapters.file_cleanup_journal import FileCleanupJournal
journal = FileCleanupJournal(sys.argv[1])
for _ in range(20):
    while True:
        with journal.claim(sys.argv[2]) as job:
            if job is not None:
                job.attempt()
                break
        time.sleep(0.001)
'''
        processes = [subprocess.Popen(
            [sys.executable, '-B', '-c', code, self.directory, job_id],
            env={**os.environ, 'PYTHONPATH': str(runtime.APP)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) for _ in range(2)]
        for process in processes:
            _, error = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, error.decode())
        with self.journal.claim(job_id) as job:
            self.assertEqual(job.data['attempts'], 40)
            self.assertIsNotNone(job.data['last_attempt_at'])

    def test_failed_atomic_replace_preserves_previous_readable_job(self):
        with self.journal.create('bucket', 'key') as job:
            before = self.journal.path(job.data['id']).read_bytes()
            with patch('adapters.file_cleanup_journal.os.replace', side_effect=OSError('Disk failure')):
                with self.assertRaises(JournalError):
                    job.update(state='uploaded')
            self.assertEqual(self.journal.path(job.data['id']).read_bytes(), before)
            self.assertEqual(job.data['state'], 'uploading')

    def test_job_file_and_directory_are_fsynced_before_upload_can_begin(self):
        from adapters import file_cleanup_journal as adapter
        original = adapter.os.fsync
        calls = []
        with patch.object(adapter.os, 'fsync', side_effect=lambda fd: (calls.append(fd), original(fd))[-1]):
            with self.journal.create('bucket', 'key') as job:
                self.assertGreaterEqual(len(calls), 3)
                self.assertTrue(self.journal.path(job.data['id']).exists())
                self.assertEqual(self.journal.path(job.data['id']).stat().st_mode & 0o777, 0o600)

    def test_s3_delete_missing_key_is_success_and_retried_put_is_uncertain(self):
        from adapters.file_storage.s3 import S3FileStorageAdapter
        from botocore.stub import Stubber
        storage = S3FileStorageAdapter('bucket', 'fake-access', 'fake-secret')
        self.addCleanup(storage.client.close)
        with Stubber(storage.client) as stub:
            stub.add_client_error('delete_object', service_error_code='NoSuchKey', http_status_code=404,
                                  expected_params={'Bucket': 'bucket', 'Key': 'absent'})
            storage.delete_file('absent')
            stub.add_response('put_object', {'ResponseMetadata': {'RetryAttempts': 1}},
                              {'Bucket': 'bucket', 'Key': 'key', 'Body': b'a', 'ContentType': 'text/plain'})
            with self.assertRaises(FileStorageError):
                storage.upload_file('key', b'a', 'text/plain')
            stub.assert_no_pending_responses()


class JournalScenarios:
    def service(self):
        return runtime.MaterialService(
            self.materials, self.launches, self.sections, self.storage,
            runtime.StoredFileService(self.files, self.materials, self.storage), self.notes, self.journal,
        )

    def create_material(self):
        return self.service().create_material(self.run['id'], 1, 'Journal test', None, runtime.upload())

    def worker(self, repository=None):
        return FileCleanupService(repository or self.files, self.storage, runtime.config.settings.S3_BUCKET, self.journal)

    def retry(self):
        for job_id in self.journal.pending():
            with self.journal.claim(job_id) as job:
                job.update(next_attempt_at=0)
        return self.worker().run()

    def fail_registration(self, *args, **kwargs):
        if self.db.get_bind().dialect.name == 'postgresql':
            self.db.execute(sa.text('SELECT 1 / 0'))
        raise sa.exc.SQLAlchemyError('Simulated database failure')

    def test_successful_registration_finishes_job_and_preserves_object(self):
        before = set(self.storage.objects)
        self.create_material()
        self.assertEqual(self.journal.pending(), [])
        self.assertEqual(self.worker().run()['processed'], 0)
        self.assertEqual(len(set(self.storage.objects) - before), 1)

    def test_database_failure_compensates_and_finishes_job(self):
        before = dict(self.storage.objects)
        with patch.object(self.materials, 'create_material', side_effect=self.fail_registration):
            with self.assertRaises(MaterialSaveFailedException):
                self.create_material()
        self.assertEqual(self.storage.objects, before)
        self.assertEqual(self.journal.pending(), [])

    def test_database_and_storage_failures_leave_durable_retry_then_recover(self):
        before = dict(self.storage.objects)
        self.storage.delete_error = True
        with patch.object(self.materials, 'create_material', side_effect=self.fail_registration):
            with self.assertRaises(MaterialSaveFailedException):
                self.create_material()
        ids = FileCleanupJournal(self.journal.directory).pending()
        self.assertEqual(len(ids), 1)
        with self.journal.claim(ids[0]) as job:
            self.assertEqual(job.data['state'], 'uploaded')
            self.assertEqual(job.data['attempts'], 1)
            self.assertEqual(job.data['last_error_code'], 'storage_deletion_failed')
            self.assertNotIn('Simulated database failure', json.dumps(job.data))
        self.assertEqual(len(self.storage.objects), len(before) + 1)
        self.storage.delete_error = False
        self.assertEqual(self.retry()['deleted'], 1)
        self.assertEqual(self.storage.objects, before)
        self.assertEqual(self.journal.pending(), [])

    def test_unknown_successful_commit_is_checked_before_compensation(self):
        before = set(self.storage.objects)
        original = self.materials.create_material

        def commit_then_disconnect(*args):
            original(*args)
            raise sa.exc.SQLAlchemyError('Commit acknowledgement was lost')

        with patch.object(self.materials, 'create_material', side_effect=commit_then_disconnect):
            with patch.object(self.storage, 'delete_file', wraps=self.storage.delete_file) as deletion:
                with self.assertRaises(MaterialSaveFailedException):
                    self.create_material()
                deletion.assert_not_called()
        self.assertEqual(self.journal.pending(), [])
        self.assertEqual(len(set(self.storage.objects) - before), 1)

    def test_unknown_replacement_commit_preserves_registered_new_file(self):
        material = self.create_material()
        original = self.materials.replace_file

        def commit_then_disconnect(*args):
            original(*args)
            raise sa.exc.SQLAlchemyError('Commit acknowledgement was lost')

        with patch.object(self.materials, 'replace_file', side_effect=commit_then_disconnect):
            with patch.object(self.storage, 'delete_file', wraps=self.storage.delete_file) as deletion:
                with self.assertRaises(MaterialFileReplacementFailedException):
                    self.service().replace_file(material['id'], 1, runtime.upload('replacement.txt'))
                deletion.assert_not_called()
        current = self.materials.get_material_by_id(material['id'], 1)
        self.assertNotEqual(current['stored_file_id'], material['stored_file_id'])
        self.assertIn(self.files.get_file_by_id(current['stored_file_id'], 1)['storage_key'], self.storage.objects)
        self.assertTrue(self.files.get_file_by_id(material['stored_file_id'], 1)['deletion_pending'])
        self.assertEqual(self.journal.pending(), [])

    def test_stale_job_after_success_is_protected_even_for_another_file_owner(self):
        with patch.object(CleanupJob, 'complete', side_effect=JournalError('Unavailable directory')):
            material = self.create_material()
        if self.db.get(User, 2) is None:
            self.db.add(User(id=2, username='second', email='second@example.com', hashed_password='unused'))
            self.db.flush()
        stored = self.db.get(StoredFile, material['stored_file_id'])
        stored.uploaded_by_id = 2
        self.db.commit()
        with patch.object(self.storage, 'delete_file', wraps=self.storage.delete_file) as deletion:
            self.assertEqual(self.retry()['protected'], 1)
            deletion.assert_not_called()
        self.assertEqual(self.journal.pending(), [])

    def test_existing_unused_metadata_uses_durable_pending_protocol(self):
        material = self.create_material()
        stored = self.files.get_file_by_id(material['stored_file_id'], 1)
        self.materials.delete_material(material['id'], 1)
        with self.journal.create(stored['bucket'], stored['storage_key']) as job:
            job.update(state='uploaded')
        self.storage.delete_error = True
        self.assertEqual(self.worker().run()['deferred'], 1)
        self.assertTrue(self.files.get_file_by_id(stored['id'], 1)['deletion_pending'])
        self.assertEqual(len(self.journal.pending()), 1)
        self.storage.delete_error = False
        self.assertEqual(self.retry()['deleted'], 1)
        self.assertIsNone(self.files.get_file_by_id(stored['id'], 1))

    def test_repeat_after_s3_delete_but_before_job_finish_is_idempotent(self):
        before = dict(self.storage.objects)
        self.storage.upload_file('already-deleted', b'a')
        with self.journal.create(runtime.config.settings.S3_BUCKET, 'already-deleted') as job:
            job.update(state='uploaded')
        with patch.object(CleanupJob, 'complete', side_effect=JournalError('Crash before job finish')):
            self.assertEqual(self.worker().run()['deferred'], 1)
        self.assertEqual(self.storage.objects, before)
        self.assertEqual(len(self.journal.pending()), 1)
        self.assertEqual(self.retry()['deleted'], 1)
        self.assertEqual(self.journal.pending(), [])

    def test_active_upload_is_not_claimed_by_cleanup(self):
        original = self.storage.upload_file

        def upload_while_cleaner_runs(*args):
            self.assertEqual(self.worker().run()['busy'], 1)
            return original(*args)

        with patch.object(self.storage, 'upload_file', side_effect=upload_while_cleaner_runs):
            self.create_material()
        self.assertEqual(self.journal.pending(), [])

    def test_unconfirmed_upload_keeps_record_even_after_successful_delete(self):
        before = dict(self.storage.objects)
        original = self.storage.upload_file

        def uncertain_put(*args):
            original(*args)
            raise FileStorageError('PUT response lost')

        with patch.object(self.storage, 'upload_file', side_effect=uncertain_put):
            with self.assertRaises(FileUploadFailedException):
                self.create_material()
        self.assertEqual(self.worker().run()['deferred'], 1)
        self.assertEqual(self.storage.objects, before)
        ids = self.journal.pending()
        self.assertEqual(len(ids), 1)
        with self.journal.claim(ids[0]) as job:
            self.assertEqual(job.data['state'], 'upload_uncertain')
            key = job.data['storage_key']
        original(key, b'a')  # A late server-side PUT must still be accounted for.
        self.assertEqual(self.retry()['deferred'], 1)
        self.assertEqual(self.storage.objects, before)
        self.assertEqual(self.journal.pending(), ids)

    def test_fsync_failure_prevents_upload(self):
        with patch('adapters.file_cleanup_journal.os.fsync', side_effect=OSError('Disk unavailable')):
            with patch.object(self.storage, 'upload_file') as upload:
                with self.assertRaises(FileJournalUnavailableException):
                    self.create_material()
                upload.assert_not_called()

    def test_state_write_failure_after_put_preserves_initial_intent(self):
        original = self.journal.write

        def fail_after_upload(data):
            if data['state'] == 'uploaded':
                raise JournalError('Disk unavailable')
            return original(data)

        with patch.object(self.journal, 'write', side_effect=fail_after_upload):
            with self.assertRaises(FileJournalUnavailableException):
                self.create_material()
        ids = self.journal.pending()
        self.assertEqual(len(ids), 1)
        with self.journal.claim(ids[0]) as job:
            self.assertEqual(job.data['state'], 'uploading')
            self.assertIn(job.data['storage_key'], self.storage.objects)

    def test_bucket_mismatch_and_corrupt_jobs_never_delete_objects(self):
        with self.journal.create('other-bucket', 'key') as job:
            job.update(state='uploaded')
        with patch.object(self.storage, 'delete_file') as deletion:
            self.assertEqual(self.worker().run()['deferred'], 1)
            ids = self.journal.pending()
            self.journal.path(ids[0]).write_text('{broken', encoding='utf-8')
            self.assertEqual(self.worker().run()['deferred'], 1)
            deletion.assert_not_called()
        self.assertEqual(self.journal.pending(), ids)

    def test_bounded_run_leaves_remaining_jobs(self):
        for index in range(3):
            with self.journal.create(runtime.config.settings.S3_BUCKET, f'absent-{index}') as job:
                job.update(state='uploaded')
        self.assertEqual(self.worker().run(limit=2)['deleted'], 2)
        self.assertEqual(len(self.journal.pending()), 1)

    def test_cli_uses_configured_journal_and_limits_work(self):
        import cleanup_files
        for index in range(2):
            with self.journal.create(runtime.config.settings.S3_BUCKET, f'cli-{index}') as job:
                job.update(state='uploaded')
        self.db.rollback()
        client = SimpleNamespace(close=Mock())
        with patch.object(runtime.database, 'SessionLocal', lambda: Session(bind=self.db.get_bind()), create=True), \
                patch.object(runtime.config.settings, 'FILE_CLEANUP_DIR', self.journal.directory, create=True), \
                patch.multiple(runtime.config.settings, S3_ACCESS_KEY='fake-access',
                               S3_SECRET_KEY=runtime.SecretStr('fake-secret'), S3_REGION='test',
                               S3_ENDPOINT='https://s3.invalid', create=True), \
                patch('adapters.file_storage.s3.S3FileStorageAdapter', return_value=self.storage), \
                patch.object(self.storage, 'client', client, create=True), \
                patch.object(sys, 'argv', ['cleanup_files.py', '--limit', '1']), \
                patch('builtins.print') as output:
            self.assertEqual(cleanup_files.main(), 0)
        self.assertEqual(json.loads(output.call_args.args[0])['deleted'], 1)
        self.assertEqual(len(self.journal.pending()), 1)
        client.close.assert_called_once()


class JournalSQLiteTests(JournalScenarios, unittest.TestCase):
    setUp = runtime.ERDTests.setUp
    tearDown = runtime.ERDTests.tearDown
    run_data = staticmethod(runtime.ERDTests.run_data)


@unittest.skipUnless(
    os.environ.get('KMS_TEST_CLEANUP_DATABASE_URL') or os.environ.get('KMS_TEST_DATABASE_URL'),
    'Нужен отдельный PostgreSQL: KMS_TEST_CLEANUP_DATABASE_URL или KMS_TEST_DATABASE_URL',
)
class JournalPostgreSQLTests(JournalScenarios, unittest.TestCase):
    tearDown = cleanup_tests.CleanupPostgreSQLTests.tearDown

    def setUp(self):
        cleanup_tests.CleanupPostgreSQLTests.setUp(self)
        directory = TemporaryDirectory(prefix='kms-pg-journal-')
        self.addCleanup(directory.cleanup)
        self.journal = FileCleanupJournal(directory.name)
        self.run = {'id': 1}
        self.launches = runtime.LaunchRepository(self.db)
        self.sections = runtime.SectionRepository(self.db)
        self.notes = runtime.NoteRepository(self.db)
        for table in ('stored_files', 'materials'):
            self.db.execute(sa.text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT max(id) FROM {table}))"
            ))
        self.db.commit()
        runtime.app.dependency_overrides[get_file_cleanup_journal] = lambda: self.journal

    def test_unavailable_postgresql_preserves_job_without_calling_s3(self):
        with self.journal.create(runtime.config.settings.S3_BUCKET, 'orphan') as job:
            job.update(state='uploaded')
        self.storage.upload_file('orphan', b'a')
        # An unreachable socket in a fresh temporary directory cannot point to
        # a developer database. This is a real driver connection failure.
        with TemporaryDirectory(prefix='kms-no-postgres-') as missing_socket:
            url = self.engine.url.update_query_dict({'host': missing_socket, 'connect_timeout': '1'})
            unavailable = sa.create_engine(url, hide_parameters=True)
            try:
                with Session(unavailable) as db:
                    with patch.object(self.storage, 'delete_file', wraps=self.storage.delete_file) as deletion:
                        result = self.worker(StoredFileRepository(db)).run()
                        self.assertEqual(result['deferred'], 1)
                        deletion.assert_not_called()
            finally:
                unavailable.dispose()
        self.assertEqual(len(self.journal.pending()), 1)
        self.assertIn('orphan', self.storage.objects)
        self.assertEqual(self.retry()['deleted'], 1)
        self.assertNotIn('orphan', self.storage.objects)

    def test_cleanup_waits_for_registration_commit_before_deciding_object_is_orphaned(self):
        bucket = runtime.config.settings.S3_BUCKET
        key = 'commit-in-flight'
        with self.journal.create(bucket, key) as job:
            job.update(state='uploaded')
        self.storage.upload_file(key, b'a')
        committing, allow_commit, cleaner_ready = Event(), Event(), Event()
        cleaner_pid = []

        def connection():
            conn = self.engine.connect()
            conn.execute(sa.text(f'SET search_path TO "{self.schema}"'))
            conn.commit()
            return conn

        def register():
            with connection() as conn, Session(bind=conn) as db:
                commit = db.commit

                def delayed_commit():
                    committing.set()
                    if not allow_commit.wait(10):
                        raise RuntimeError('Test commit release timed out')
                    commit()

                with patch.object(db, 'commit', side_effect=delayed_commit):
                    return runtime.MaterialRepository(db).create_material(1, {'title': 'Concurrent'}, {
                        'bucket': bucket, 'storage_key': key, 'original_filename': 'test.txt',
                        'mime_type': 'text/plain', 'size_bytes': 1, 'uploaded_by_id': 1,
                    })

        def clean():
            with connection() as conn, Session(bind=conn) as db:
                cleaner_pid.append(conn.scalar(sa.text('SELECT pg_backend_pid()')))
                conn.commit()
                cleaner_ready.set()
                return self.worker(StoredFileRepository(db)).run()

        with ThreadPoolExecutor(max_workers=2) as pool:
            registration = pool.submit(register)
            try:
                self.assertTrue(committing.wait(5))
                cleanup = pool.submit(clean)
                self.assertTrue(cleaner_ready.wait(5))
                waiting = False
                for _ in range(100):
                    waiting = bool(self.db.scalar(sa.text(
                        "SELECT count(*) FROM pg_locks WHERE pid=:pid AND locktype='advisory' AND NOT granted"
                    ), {'pid': cleaner_pid[0]}))
                    if waiting:
                        break
                    time.sleep(0.01)
                self.assertTrue(waiting, 'Cleanup must wait for the registration transaction')
                self.assertIn(key, self.storage.objects)
            finally:
                allow_commit.set()
            registration.result(timeout=5)
            self.assertEqual(cleanup.result(timeout=5)['protected'], 1)
        self.assertIn(key, self.storage.objects)
        self.assertEqual(self.journal.pending(), [])

    def test_concurrent_cleanup_processes_delete_only_once(self):
        with self.journal.create(runtime.config.settings.S3_BUCKET, 'concurrent-orphan') as job:
            job.update(state='uploaded')
        code = '''
import os, sys, time
import test_erd as runtime
import sqlalchemy as sa
from sqlalchemy.orm import Session
from adapters.file_cleanup_journal import FileCleanupJournal
from repositories.stored_files import StoredFileRepository
from services.file_cleanup import FileCleanupService
class Storage:
    def delete_file(self, key):
        fd = os.open(sys.argv[3], os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            os.write(fd, b'delete\\n')
            os.fsync(fd)
        finally:
            os.close(fd)
        time.sleep(0.05)
engine = sa.create_engine(os.environ['KMS_TEST_CLEANUP_DATABASE_URL'], hide_parameters=True)
try:
    with engine.connect() as conn:
        conn.execute(sa.text('SET search_path TO "' + sys.argv[2] + '"'))
        conn.commit()
        with Session(bind=conn) as db:
            FileCleanupService(StoredFileRepository(db), Storage(), runtime.config.settings.S3_BUCKET,
                               FileCleanupJournal(sys.argv[1])).run(1)
finally:
    engine.dispose()
'''
        record = self.journal.directory / 'test-deletions'
        env = {**os.environ,
               'PYTHONPATH': os.pathsep.join((str(runtime.APP), str(Path(__file__).parent))),
               'KMS_TEST_CLEANUP_DATABASE_URL': self.engine.url.render_as_string(hide_password=False)}
        processes = [subprocess.Popen(
            [sys.executable, '-B', '-c', code, str(self.journal.directory), self.schema, str(record)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) for _ in range(2)]
        for process in processes:
            _, error = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, error.decode())
        self.assertEqual(record.read_text().splitlines(), ['delete'])
        self.assertEqual(self.journal.pending(), [])
