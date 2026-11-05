import logging
import time

from sqlalchemy.exc import SQLAlchemyError

from adapters.file_cleanup_journal import JournalError
from adapters.file_storage.base import FileStorageError, StoredFileNotFound
from core.exceptions import AppException
from repositories.stored_files import FileUnavailableError
from services.stored_files import StoredFileService


logger = logging.getLogger(__name__)


class FileCleanupService:
    def __init__(self, repository, storage, bucket, journal):
        self.repository = repository
        self.storage = storage
        self.bucket = bucket
        self.journal = journal

    def process(self, job):
        job.attempt()  # If this cannot be persisted, do not touch S3.
        if job.data['bucket'] != self.bucket:
            job.update(last_error_code='bucket_not_configured')
            return 'deferred'
        try:
            # Compensation starts only after registration has returned/failed.
            # Clear stale snapshots and failed transactions before verification.
            self.repository.db.rollback()
            with self.repository.cleanup_attempt():
                stored = self.repository.get_object_for_cleanup(job.data['bucket'], job.data['storage_key'])
                if stored is not None and stored['used']:
                    job.complete()
                    return 'protected'
                if stored is not None:
                    # Reuse row locks, durable deletion_pending, reference checks
                    # and the existing two-phase physical/metadata deletion.
                    StoredFileService(self.repository, storage=self.storage).delete_file(
                        stored['id'], stored['uploaded_by_id'])
                else:
                    try:
                        self.storage.delete_file(job.data['storage_key'])
                    except StoredFileNotFound:
                        pass
                if job.data['state'] != 'uploaded':
                    # A crashed/timed-out PUT may still complete at the server.
                    # Never discard its only recovery record based on DELETE.
                    job.update(state='upload_uncertain', last_error_code='upload_completion_unknown')
                    return 'deferred'
                job.complete()
                return 'deleted'
        except (SQLAlchemyError, FileUnavailableError):
            job.update(last_error_code='database_verification_failed')
        except FileStorageError:
            job.update(last_error_code='storage_deletion_failed')
        except AppException:
            job.update(last_error_code='file_deletion_pending')
        return 'deferred'

    def run(self, limit=100):
        if not 1 <= limit <= 10000:
            raise ValueError('limit must be between 1 and 10000')
        results = dict(processed=0, deleted=0, protected=0, deferred=0, busy=0, not_due=0)
        for job_id in self.journal.pending():
            if results['processed'] >= limit:
                break
            counted = False
            try:
                with self.journal.claim(job_id) as job:
                    if job is None:
                        results['busy'] += 1
                        continue
                    if job.data['next_attempt_at'] > time.time():
                        results['not_due'] += 1
                        continue
                    results['processed'] += 1
                    counted = True
                    outcome = self.process(job)
                    results[outcome] += 1
            except JournalError:
                # Do not log raw file contents or exception messages.
                logger.error('Cleanup journal job unavailable: %s', job_id)
                if not counted:
                    results['processed'] += 1
                results['deferred'] += 1
        return results
