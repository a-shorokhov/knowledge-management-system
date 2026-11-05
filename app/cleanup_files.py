"""Internal bounded cleanup command; does not run API startup or migrations."""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(description='Retry durable file cleanup jobs')
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error('--limit must be between 1 and 10000')

    import models
    from adapters.file_cleanup_journal import FileCleanupJournal, JournalError
    from adapters.file_storage.s3 import S3FileStorageAdapter
    from core.config import settings
    from core.database import SessionLocal
    from repositories.stored_files import StoredFileRepository
    from services.file_cleanup import FileCleanupService

    storage = S3FileStorageAdapter(
        settings.S3_BUCKET, settings.S3_ACCESS_KEY, settings.S3_SECRET_KEY.get_secret_value(),
        settings.S3_REGION, settings.S3_ENDPOINT,
    )
    try:
        with SessionLocal() as db:
            result = FileCleanupService(
                StoredFileRepository(db), storage, settings.S3_BUCKET,
                FileCleanupJournal(settings.FILE_CLEANUP_DIR),
            ).run(args.limit)
        print(json.dumps(result))
        return 1 if result['deferred'] else 0
    except JournalError:
        print(json.dumps({'error': 'cleanup_journal_unavailable'}))
        return 1
    finally:
        storage.client.close()


if __name__ == '__main__':
    raise SystemExit(main())
