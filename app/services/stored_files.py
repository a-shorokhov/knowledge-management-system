import logging

from fastapi import Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.exceptions import (
    AppException,
    DownloadUrlFailedException,
    FileCleanupFailedException,
    FileDeletionConflictException,
    FileDeletionPendingException,
    FileDeletionStartFailedException,
    FileInUseException,
    FileNotFoundException,
    FileRecordDeletionPendingException,
    FileStorageNotConfiguredException,
    MaterialNotFoundException,
    StorageDeletionPendingException,
    StoredObjectNotFoundException,
    UnusedFileDeletionFailedException,
)
from adapters.file_storage.base import FileStorageAdapter, FileStorageError, StoredFileNotFound
from core.config import settings
from core.depends import get_file_storage
from repositories.materials import MaterialRepository
from repositories.stored_files import FileInUseError, FileUnavailableError, StoredFileRepository


logger = logging.getLogger(__name__)
DOWNLOAD_LIFETIME = 3600


class StoredFileService:
    def __init__(
        self,
        repository: StoredFileRepository = Depends(),
        materials: MaterialRepository = Depends(),
        storage: FileStorageAdapter = Depends(get_file_storage),
    ):
        self.repository = repository
        self.materials = materials
        self.storage = storage

    def get_all_files(self, user_id: int):
        return {"success": True, "data": self.repository.get_all_files(user_id)}

    def get_file_by_id(self, file_id: int, user_id: int):
        stored_file = self.repository.get_file_by_id(file_id, user_id)
        if stored_file is None:
            raise FileNotFoundException()

        return {"success": True, **stored_file}

    def get_download_url(self, file_id: int, user_id: int):
        stored_file = self.repository.get_file_by_id(file_id, user_id)
        if stored_file is None:
            raise FileNotFoundException()
        if stored_file["deletion_pending"]:
            raise FileDeletionPendingException()
        if stored_file["bucket"] != settings.S3_BUCKET:
            raise FileStorageNotConfiguredException()

        try:
            url = self.storage.get_download_url(stored_file["storage_key"], DOWNLOAD_LIFETIME)
        except StoredFileNotFound:
            raise StoredObjectNotFoundException()
        except FileStorageError:
            logger.exception("Ошибка получения ссылки на файл")
            raise DownloadUrlFailedException()

        return {"success": True, "url": url, "expires_in": DOWNLOAD_LIFETIME}

    def get_material_download_url(self, material_id: int, user_id: int):
        material = self.materials.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundException()

        return self.get_download_url(material["stored_file_id"], user_id)

    def delete_unused_files(self, file_ids: list[int], user_id: int):
        failed_ids = []
        for file_id in sorted(set(file_ids)):
            try:
                self.delete_file_if_unused(file_id, user_id)
            except AppException:
                failed_ids.append(file_id)

        if failed_ids:
            raise FileCleanupFailedException(failed_ids)

        return {"success": True}

    def delete_file_if_unused(self, file_id: int, user_id: int):
        try:
            stored_file = self.repository.get_file_by_id(file_id, user_id)
            if stored_file is None or self.repository.is_file_used(file_id):
                return {"success": True}

            return self.delete_file(file_id, user_id)
        except SQLAlchemyError:
            logger.exception("Ошибка проверки неиспользуемого файла")
            raise UnusedFileDeletionFailedException()

    def delete_file(self, file_id: int, user_id: int):
        try:
            stored_file = self.repository.get_file_by_id(file_id, user_id)
            if stored_file is None:
                raise FileNotFoundException()
            if stored_file["bucket"] != settings.S3_BUCKET:
                raise FileStorageNotConfiguredException()

            stored_file = self.repository.mark_file_for_deletion(file_id, user_id)
        except FileInUseError:
            raise FileInUseException()
        except SQLAlchemyError:
            logger.exception("Ошибка сохранения намерения удалить файл")
            raise FileDeletionStartFailedException()

        if stored_file is None:
            raise FileNotFoundException()

        try:
            self.storage.delete_file(stored_file["storage_key"])
        except FileStorageError:
            logger.exception("Ошибка удаления файла из S3")
            raise StorageDeletionPendingException()

        try:
            self.repository.delete_file(file_id, user_id)
        except (IntegrityError, FileInUseError, FileUnavailableError):
            raise FileDeletionConflictException()
        except SQLAlchemyError:
            logger.exception("Ошибка завершения удаления файла в БД")
            raise FileRecordDeletionPendingException()

        return {"success": True, "message": "Файл удалён из хранилища и базы данных"}
