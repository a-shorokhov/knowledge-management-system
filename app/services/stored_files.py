import logging

from fastapi import Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
            return {"success": False, "message": "Файл не найден"}

        return {"success": True, **stored_file}

    def get_download_url(self, file_id: int, user_id: int):
        stored_file = self.repository.get_file_by_id(file_id, user_id)
        if stored_file is None:
            return {"success": False, "message": "Файл не найден"}
        if stored_file["deletion_pending"]:
            return {"success": False, "message": "Файл ожидает удаления", "status_code": 409}
        if stored_file["bucket"] != settings.S3_BUCKET:
            return {"success": False, "message": "Хранилище этого файла не настроено", "status_code": 503}

        try:
            url = self.storage.get_download_url(stored_file["storage_key"], DOWNLOAD_LIFETIME)
        except StoredFileNotFound:
            return {"success": False, "message": "Файл не найден в хранилище"}
        except FileStorageError:
            logger.exception("Ошибка получения ссылки на файл")
            return {"success": False, "message": "Не удалось получить ссылку на файл", "status_code": 503}

        return {"success": True, "url": url, "expires_in": DOWNLOAD_LIFETIME}

    def get_material_download_url(self, material_id: int, user_id: int):
        material = self.materials.get_material_by_id(material_id, user_id)
        if material is None:
            return {"success": False, "message": "Материал не найден"}

        return self.get_download_url(material["stored_file_id"], user_id)

    def delete_unused_files(self, file_ids: list[int], user_id: int):
        failed_ids = []
        for file_id in sorted(set(file_ids)):
            result = self.delete_file_if_unused(file_id, user_id)
            if not result["success"]:
                failed_ids.append(file_id)

        if failed_ids:
            paths = ", ".join(f"DELETE /stored-files/{file_id}" for file_id in failed_ids)
            return {"success": False, "message": f"Не удалось завершить очистку файлов. Повторите: {paths}", "status_code": 503}

        return {"success": True}

    def delete_file_if_unused(self, file_id: int, user_id: int):
        try:
            stored_file = self.repository.get_file_by_id(file_id, user_id)
            if stored_file is None or self.repository.is_file_used(file_id):
                return {"success": True}

            return self.delete_file(file_id, user_id)
        except SQLAlchemyError:
            logger.exception("Ошибка проверки неиспользуемого файла")
            return {"success": False, "message": "Не удалось удалить неиспользуемый файл", "status_code": 503}

    def delete_file(self, file_id: int, user_id: int):
        try:
            stored_file = self.repository.get_file_by_id(file_id, user_id)
            if stored_file is None:
                return {"success": False, "message": "Файл не найден"}
            if stored_file["bucket"] != settings.S3_BUCKET:
                return {"success": False, "message": "Хранилище этого файла не настроено", "status_code": 503}

            stored_file = self.repository.mark_file_for_deletion(file_id, user_id)
        except FileInUseError:
            return {"success": False, "message": "Файл используется материалами. Сначала удалите их или замените файл", "status_code": 409}
        except SQLAlchemyError:
            logger.exception("Ошибка сохранения намерения удалить файл")
            return {"success": False, "message": "Не удалось начать удаление файла. Повторите запрос", "status_code": 503}

        if stored_file is None:
            return {"success": False, "message": "Файл не найден"}

        try:
            self.storage.delete_file(stored_file["storage_key"])
        except FileStorageError:
            logger.exception("Ошибка удаления файла из S3")
            return {"success": False, "message": "Файл ожидает удаления из хранилища. Повторите запрос", "status_code": 503}

        try:
            self.repository.delete_file(file_id, user_id)
        except (IntegrityError, FileInUseError, FileUnavailableError):
            return {"success": False, "message": "Не удалось завершить удаление файла. Повторите запрос", "status_code": 409}
        except SQLAlchemyError:
            logger.exception("Ошибка завершения удаления файла в БД")
            return {"success": False, "message": "Объект удалён из S3, запись помечена как ожидающая удаления. Повторите запрос", "status_code": 503}

        return {"success": True, "message": "Файл удалён из хранилища и базы данных"}
