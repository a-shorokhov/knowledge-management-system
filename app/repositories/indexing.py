from datetime import datetime, timezone

from sqlalchemy import delete, select, text

from models.document_chunks import DocumentChunk
from models.enums import FileIndexStatus
from models.materials import Material
from models.stored_files import StoredFile
from repositories.stored_files import StoredFileRepository


LOCK_NAMESPACE = 493851


class IndexingRepository:
    def __init__(self, db):
        self.db = db
        self.claimed_id = None

    def claim(self):
        ids = list(self.db.scalars(select(StoredFile.id).where(
            StoredFile.indexing_status.in_([FileIndexStatus.pending, FileIndexStatus.processing]),
            StoredFile.deletion_pending.is_(False),
            select(Material.id).where(Material.stored_file_id == StoredFile.id).exists(),
        ).order_by(StoredFile.id).limit(100)))
        self.db.commit()
        for file_id in ids:
            acquired = self.db.scalar(text('SELECT pg_try_advisory_lock(:namespace, :id)'), {'namespace': LOCK_NAMESPACE, 'id': file_id})
            self.db.commit()
            if not acquired:
                continue
            self.claimed_id = file_id
            row = self.db.scalar(select(StoredFile).where(StoredFile.id == file_id).with_for_update().execution_options(populate_existing=True))
            if row is None or row.deletion_pending or row.indexing_status not in (FileIndexStatus.pending, FileIndexStatus.processing):
                self.db.rollback()
                self.release()
                continue
            row.indexing_status = FileIndexStatus.processing
            row.indexing_error_code = None
            row.indexed_at = None
            result = StoredFileRepository._to_dict(row)
            self.db.commit()
            return result
        return None

    def finish(self, file_id, chunks):
        try:
            row = self.db.scalar(select(StoredFile).where(StoredFile.id == file_id).with_for_update().execution_options(populate_existing=True))
            if row is None or row.deletion_pending or row.indexing_status != FileIndexStatus.processing:
                self.db.rollback()
                return False
            self.db.execute(delete(DocumentChunk).where(DocumentChunk.stored_file_id == file_id))
            self.db.add_all([DocumentChunk(stored_file_id=file_id, **chunk) for chunk in chunks])
            row.indexing_status = FileIndexStatus.ready
            row.indexing_error_code = None
            row.indexed_at = datetime.now(timezone.utc)
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def fail(self, file_id, code):
        self.db.rollback()
        row = self.db.scalar(select(StoredFile).where(StoredFile.id == file_id).with_for_update().execution_options(populate_existing=True))
        if row is not None and not row.deletion_pending:
            row.indexing_status = FileIndexStatus.failed
            row.indexing_error_code = code
            row.indexed_at = None
        self.db.commit()

    def release(self):
        self.db.rollback()
        if self.claimed_id is not None:
            self.db.execute(text('SELECT pg_advisory_unlock(:namespace, :id)'), {'namespace': LOCK_NAMESPACE, 'id': self.claimed_id})
            self.db.commit()
            self.claimed_id = None

    def reindex(self, file_id, user_id):
        try:
            row = self.db.scalar(select(StoredFile).where(
                StoredFile.id == file_id, StoredFile.uploaded_by_id == user_id,
            ).with_for_update().execution_options(populate_existing=True))
            if row is None:
                self.db.rollback()
                return None
            if row.deletion_pending:
                self.db.rollback()
                return 'deletion_pending'
            if row.indexing_status == FileIndexStatus.processing:
                self.db.rollback()
                return 'processing'
            row.indexing_status = FileIndexStatus.pending
            row.indexing_error_code = None
            row.indexed_at = None
            result = StoredFileRepository._to_dict(row)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise
