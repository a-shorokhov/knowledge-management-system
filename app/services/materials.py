import logging
from pathlib import Path
from uuid import uuid4

from fastapi import Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from adapters.file_storage.base import FileStorageAdapter, FileStorageError
from core.config import settings
from core.depends import get_file_storage
from models.enums import MaterialKind
from repositories.launches import LaunchRepository
from repositories.materials import MaterialRepository
from repositories.notes import NoteRepository
from repositories.sections import SectionRepository
from repositories.stored_files import FileUnavailableError
from schemas.materials import CopyMaterialRequest, MaterialUpload, UpdateMaterialRequest
from services.stored_files import StoredFileService
from services.file_validation import is_valid_file_content


logger = logging.getLogger(__name__)
MAX_FILE_SIZE = 5 * 1024 * 1024
ALLOWED_MATERIAL_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "text/plain": "txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/csv": "csv",
}



class MaterialService:
    def __init__(
        self,
        repository: MaterialRepository = Depends(),
        launches: LaunchRepository = Depends(),
        sections: SectionRepository = Depends(),
        storage: FileStorageAdapter = Depends(get_file_storage),
        files: StoredFileService = Depends(),
        notes: NoteRepository = Depends(),
    ):
        self.repository = repository
        self.launches = launches
        self.sections = sections
        self.storage = storage
        self.files = files
        self.notes = notes

    def _upload_file(self, user_id: int, file: MaterialUpload):
        extension = ALLOWED_MATERIAL_TYPES.get(file.content_type)

        if extension is None:
            return {
                "success": False,
                "message": "Неподдерживаемый тип файла. Разрешены: png, jpg, jpeg, txt, docx, xlsx, pdf, pptx, csv",
                "status_code": 400,
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

        filename_extension = Path(filename).suffix.lower().lstrip(".")
        if filename_extension == "jpeg":
            filename_extension = "jpg"
        if filename_extension != extension:
            return {
                "success": False,
                "message": "Расширение файла не соответствует заявленному типу",
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

        if not is_valid_file_content(data, extension):
            return {
                "success": False,
                "message": "Содержимое файла не соответствует заявленному формату или файл повреждён",
                "status_code": 400,
            }

        key = f"materials/{uuid4().hex}/{filename}"

        if len(key.encode("utf-8")) > 1024:
            return {
                "success": False,
                "message": "Слишком длинное имя файла",
                "status_code": 400,
            }

        try:
            self.storage.upload_file(key, data, file.content_type)
        except FileStorageError:
            logger.exception("Ошибка загрузки материала в S3")
            return {
                "success": False,
                "message": "Не удалось загрузить файл в хранилище",
                "status_code": 503,
            }

        return {
            "success": True,
            "data": {
                "bucket": settings.S3_BUCKET,
                "storage_key": key,
                "original_filename": filename,
                "mime_type": file.content_type,
                "size_bytes": len(data),
                "uploaded_by_id": user_id,
            },
        }

    def _remove_uploaded_file(self, key: str):
        try:
            self.storage.delete_file(key)
        except FileStorageError:
            logger.exception("Не удалось убрать файл после ошибки БД: %s", key)

    def create_material(self, launch_id: int, user_id: int, title: str, description: str | None, file: MaterialUpload, section_id: int | None = None, kind: MaterialKind = MaterialKind.other, position: int = 0):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            return {"success": False, "message": "Запуск не найден"}

        if section_id is not None:
            section = self.sections.get_section_by_id(section_id, user_id)
            if section is None or section["launch_id"] != launch_id:
                return {"success": False, "message": "Раздел не найден в этом запуске"}

        uploaded = self._upload_file(user_id, file)
        if not uploaded["success"]:
            return uploaded

        try:
            material = self.repository.create_material(launch_id, {
                "title": title,
                "description": description,
                "section_id": section_id,
                "kind": kind,
                "position": position,
            }, uploaded["data"])
        except SQLAlchemyError:
            logger.exception("Ошибка сохранения материала в БД")
            self._remove_uploaded_file(uploaded["data"]["storage_key"])
            return {"success": False, "message": "Не удалось сохранить материал в базе данных", "status_code": 503}

        return {"success": True, **material}

    def get_all_materials(self, launch_id: int, user_id: int):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            return {"success": False, "message": "Запуск не найден"}

        return {"success": True, "data": self.repository.get_all_materials(launch_id, user_id)}

    def get_material_by_id(self, material_id: int, user_id: int):
        material = self.repository.get_material_by_id(material_id, user_id)
        if material is None:
            return {"success": False, "message": "Материал не найден"}

        return {"success": True, **material}

    def edit_material(self, material_id: int, user_id: int, data: UpdateMaterialRequest):
        changes = data.model_dump(exclude_unset=True)
        try:
            with self.repository.transaction():
                material = self.repository.lock_material(material_id, user_id)
                if material is None:
                    return {"success": False, "message": "Материал не найден"}
                if data.section_id is not None:
                    section = self.sections.get_section_by_id(data.section_id, user_id)
                    if section is None or section["launch_id"] != material["launch_id"]:
                        return {"success": False, "message": "Раздел не найден в этом запуске"}
                if "section_id" in changes and changes["section_id"] != material["section_id"]:
                    section_ids = self.notes.get_material_section_ids(material_id)
                    if any(section_id != changes["section_id"] for section_id in section_ids):
                        return {"success": False, "message": "У материала есть заметки с привязкой к текущему разделу. Сначала отвяжите их от раздела или удалите", "status_code": 409}
                material = self.repository.edit_material(material_id, user_id, changes)
        except IntegrityError:
            return {"success": False, "message": "Связанные данные изменились, повторите запрос", "status_code": 409}
        return {"success": True, **material}

    def replace_file(self, material_id: int, user_id: int, file: MaterialUpload):
        if self.repository.get_material_by_id(material_id, user_id) is None:
            return {"success": False, "message": "Материал не найден"}

        uploaded = self._upload_file(user_id, file)
        if not uploaded["success"]:
            return uploaded

        try:
            material = self.repository.replace_file(material_id, user_id, uploaded["data"])
        except SQLAlchemyError:
            logger.exception("Ошибка замены файла в БД")
            self._remove_uploaded_file(uploaded["data"]["storage_key"])
            return {"success": False, "message": "Не удалось заменить файл в базе данных", "status_code": 503}

        if material is None:
            self._remove_uploaded_file(uploaded["data"]["storage_key"])
            return {"success": False, "message": "Материал не найден"}

        previous_file_id = material.pop("previous_stored_file_id")
        cleanup = self.files.delete_file_if_unused(previous_file_id, user_id)
        if not cleanup["success"]:
            return {
                "success": False,
                "message": f"Файл материала заменён, но старый файл №{previous_file_id} не удалось удалить. Повторите удаление через DELETE /stored-files/{previous_file_id}",
                "status_code": 503,
            }

        return {"success": True, **material}

    def copy_material(self, material_id: int, user_id: int, data: CopyMaterialRequest):
        material = self.repository.get_material_by_id(material_id, user_id)
        if material is None:
            return {"success": False, "message": "Материал не найден"}

        source = self.launches.get_launch_by_id(material["launch_id"], user_id)
        target = self.launches.get_launch_by_id(data.launch_id, user_id)
        if source is None or target is None:
            return {"success": False, "message": "Запуск не найден"}
        if source["module_id"] != target["module_id"]:
            return {"success": False, "message": "Копирование разрешено только между запусками одного модуля", "status_code": 400}
        if source["id"] == target["id"]:
            return {"success": False, "message": "Выберите другой запуск", "status_code": 400}

        if data.section_id is not None:
            section = self.sections.get_section_by_id(data.section_id, user_id)
            if section is None or section["launch_id"] != target["id"]:
                return {"success": False, "message": "Раздел не найден в целевом запуске"}

        try:
            copy = self.repository.copy_material(material_id, user_id, data.model_dump())
        except FileUnavailableError:
            return {"success": False, "message": "Файл удаляется или уже недоступен для копирования", "status_code": 409}
        except IntegrityError:
            return {"success": False, "message": "Связанные данные изменились, повторите запрос", "status_code": 409}

        if copy is None:
            return {"success": False, "message": "Материал не найден"}

        return {"success": True, **copy}

    def delete_material(self, material_id: int, user_id: int):
        try:
            material = self.repository.delete_material(material_id, user_id)
        except IntegrityError:
            return {"success": False, "message": "Связанные данные изменились, повторите запрос", "status_code": 409}
        except SQLAlchemyError:
            logger.exception("Ошибка удаления материала из БД")
            return {"success": False, "message": "Не удалось удалить материал из базы данных", "status_code": 503}

        if material is None:
            return {"success": False, "message": "Материал не найден"}

        file_id = material["stored_file_id"]
        cleanup = self.files.delete_file_if_unused(file_id, user_id)
        if not cleanup["success"]:
            return {
                "success": False,
                "message": f"Материал удалён, но файл №{file_id} не удалось удалить. Повторите удаление через DELETE /stored-files/{file_id}",
                "status_code": 503,
            }

        return {"success": True, "message": "Материал удалён"}
