import logging
from uuid import uuid4

from fastapi import Depends, UploadFile
from sqlalchemy.exc import SQLAlchemyError

from adapters.file_storage.base import FileStorageAdapter, FileStorageError
from core.depends import get_file_storage
from repositories.launches import LaunchRepository
from repositories.materials import MaterialRepository


logger = logging.getLogger(__name__)
MAX_FILE_SIZE = 5 * 1024 * 1024


class MaterialService:
    def __init__(
        self,
        repository: MaterialRepository = Depends(),
        launches: LaunchRepository = Depends(),
        storage: FileStorageAdapter = Depends(get_file_storage),
    ):
        self.repository = repository
        self.launches = launches
        self.storage = storage

    def create_material(self, launch_id: int, user_id: int, title: str, description: str | None, file: UploadFile):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            return {
                "success": False,
                "message": "Запуск не найден",
            }

        filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]

        if (
            not filename.strip()
            or filename in {".", ".."}
            or len(filename) > 255
            or any(ord(character) < 32 or ord(character) == 127 for character in filename)
        ):
            return {
                "success": False,
                "message": "Некорректное имя файла",
                "status_code": 400,
            }

        if file.size is not None and file.size > MAX_FILE_SIZE:
            return {
                "success": False,
                "message": "Размер файла превышает 5 МиБ",
                "status_code": 413,
            }

        data = file.file.read(MAX_FILE_SIZE + 1)

        if not data:
            return {
                "success": False,
                "message": "Нельзя загрузить пустой файл",
                "status_code": 400,
            }

        if len(data) > MAX_FILE_SIZE:
            return {
                "success": False,
                "message": "Размер файла превышает 5 МиБ",
                "status_code": 413,
            }

        key = f"materials/{uuid4().hex}/{filename}"

        if len(key.encode("utf-8")) > 1024:
            return {
                "success": False,
                "message": "Слишком длинное имя файла",
                "status_code": 400,
            }

        try:
            self.storage.upload_file(key, data)
        except FileStorageError:
            logger.exception("Ошибка загрузки материала в S3")
            return {
                "success": False,
                "message": "Не удалось загрузить файл в хранилище",
                "status_code": 503,
            }

        try:
            material = self.repository.create_material(launch_id, {
                "title": title,
                "description": description,
                "original_filename": filename,
                "storage_key": key,
            })
        except SQLAlchemyError:
            logger.exception("Ошибка сохранения материала в БД")

            try:
                self.storage.delete_file(key)
            except FileStorageError:
                logger.exception("Не удалось убрать файл после ошибки БД: %s", key)

            return {
                "success": False,
                "message": "Не удалось сохранить материал в базе данных",
                "status_code": 503,
            }

        return {
            "success": True,
            "id": material["id"],
            "launch_id": material["launch_id"],
            "title": material["title"],
            "description": material["description"],
            "original_filename": material["original_filename"],
            "created_at": material["created_at"],
        }

    def get_all_materials(self, launch_id: int, user_id: int):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            return {
                "success": False,
                "message": "Запуск не найден",
            }

        return {
            "success": True,
            "data": self.repository.get_all_materials(launch_id, user_id),
        }

    def delete_material(self, material_id: int, user_id: int):
        material = self.repository.get_material_by_id(material_id, user_id)

        if material is None:
            return {
                "success": False,
                "message": "Материал не найден",
            }

        try:
            self.storage.delete_file(material["storage_key"])
        except FileStorageError:
            logger.exception("Ошибка удаления материала из S3")
            return {
                "success": False,
                "message": "Не удалось удалить файл из хранилища",
                "status_code": 503,
            }

        try:
            deleted = self.repository.delete_material(material_id, user_id)
        except SQLAlchemyError:
            logger.exception("Ошибка удаления материала из БД")
            return {
                "success": False,
                "message": "Не удалось удалить материал из базы данных",
                "status_code": 503,
            }

        if not deleted:
            return {
                "success": False,
                "message": "Материал не найден",
            }

        return {
            "success": True,
            "message": "Материал удалён",
        }