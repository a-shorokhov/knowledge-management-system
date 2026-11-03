from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import get_db
from models.materials import Material
from models.stored_files import StoredFile


class FileInUseError(Exception):
    pass


class FileUnavailableError(Exception):
    pass


class StoredFileRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(stored_file: StoredFile):
        return {
            "id": stored_file.id,
            "bucket": stored_file.bucket,
            "storage_key": stored_file.storage_key,
            "original_filename": stored_file.original_filename,
            "mime_type": stored_file.mime_type,
            "size_bytes": stored_file.size_bytes,
            "uploaded_by_id": stored_file.uploaded_by_id,
            "deletion_pending": stored_file.deletion_pending,
            "indexing_status": stored_file.indexing_status,
            "indexing_error_code": stored_file.indexing_error_code,
            "indexed_at": stored_file.indexed_at,
            "created_at": stored_file.created_at,
        }

    def _get_owned_file(self, file_id: int, user_id: int):
        return self.db.scalar(
            select(StoredFile)
            .where(StoredFile.id == file_id, StoredFile.uploaded_by_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def get_file_by_id(self, file_id: int, user_id: int):
        stored_file = self._get_owned_file(file_id, user_id)
        return self._to_dict(stored_file) if stored_file is not None else None

    def get_all_files(self, user_id: int):
        files = self.db.scalars(select(StoredFile).where(StoredFile.uploaded_by_id == user_id).order_by(StoredFile.id)).all()
        return {stored_file.id: self._to_dict(stored_file) for stored_file in files}

    def is_file_used(self, file_id: int):
        return self.db.scalar(select(Material.id).where(Material.stored_file_id == file_id).limit(1)) is not None

    def lock_files(self, file_ids: list[int]):
        return self.db.scalars(
            select(StoredFile)
            .where(StoredFile.id.in_(file_ids))
            .order_by(StoredFile.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()

    def mark_unused_files(self, file_ids: list[int]):
        files = self.lock_files(file_ids)
        used_ids = set(self.db.scalars(select(Material.stored_file_id).where(Material.stored_file_id.in_(file_ids))).all())
        for stored_file in files:
            if stored_file.id not in used_ids:
                stored_file.deletion_pending = True
        self.db.flush()

    def mark_file_for_deletion(self, file_id: int, user_id: int):
        try:
            stored_file = self._get_owned_file(file_id, user_id)
            if stored_file is None:
                return None
            if self.is_file_used(file_id):
                raise FileInUseError

            stored_file.deletion_pending = True
            self.db.flush()
            result = self._to_dict(stored_file)
            self.db.commit()
        except (SQLAlchemyError, FileInUseError):
            self.db.rollback()
            raise

        return result

    def delete_file(self, file_id: int, user_id: int):
        try:
            stored_file = self._get_owned_file(file_id, user_id)
            if stored_file is None:
                return False
            if not stored_file.deletion_pending:
                raise FileUnavailableError
            if self.is_file_used(file_id):
                raise FileInUseError

            self.db.delete(stored_file)
            self.db.commit()
        except (SQLAlchemyError, FileInUseError, FileUnavailableError):
            self.db.rollback()
            raise

        return True
