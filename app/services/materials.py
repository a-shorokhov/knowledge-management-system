import logging
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.exceptions import (
    AppException,
    CrossModuleCopyException,
    DeletedMaterialCleanupFailedException,
    EmptyFileException,
    FileExtensionMismatchException,
    FileTooLargeException,
    FileUnavailableForCopyException,
    FileUploadFailedException,
    FileJournalUnavailableException,
    FilenameTooLongException,
    InvalidFileContentException,
    InvalidFilenameException,
    LaunchNotFoundException,
    MaterialDeletionFailedException,
    MaterialFileReplacementFailedException,
    MaterialNotFoundException,
    MaterialSaveFailedException,
    MaterialSectionHasNotesException,
    RelatedDataChangedException,
    ReplacedFileCleanupFailedException,
    SameLaunchCopyException,
    SectionNotFoundInLaunchException,
    SectionNotFoundInTargetLaunchException,
    UnsupportedFileTypeException,
)
from adapters.file_storage.base import FileStorageAdapter, FileStorageError
from adapters.file_cleanup_journal import FileCleanupJournal, JournalError
from core.config import settings
from core.depends import get_file_cleanup_journal, get_file_storage
from models.enums import MaterialKind
from repositories.launches import LaunchRepository
from repositories.materials import MaterialRepository
from repositories.notes import NoteRepository
from repositories.sections import SectionRepository
from repositories.stored_files import FileUnavailableError
from schemas.materials import CopyMaterialRequest, MaterialUpload, UpdateMaterialRequest
from services.stored_files import StoredFileService
from services.file_validation import is_valid_file_content
from services.file_cleanup import FileCleanupService


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
        journal: FileCleanupJournal = Depends(get_file_cleanup_journal),
    ):
        self.repository = repository
        self.launches = launches
        self.sections = sections
        self.storage = storage
        self.files = files
        self.notes = notes
        self.journal = journal

    @contextmanager
    def _upload_file(self, user_id: int, file: MaterialUpload):
        extension = ALLOWED_MATERIAL_TYPES.get(file.content_type)

        if extension is None:
            raise UnsupportedFileTypeException()

        filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]

        if (
            not filename.strip()
            or filename in {".", ".."}
            or len(filename) > 255
            or any(ord(character) < 32 or ord(character) == 127 for character in filename)
        ):
            raise InvalidFilenameException()

        filename_extension = Path(filename).suffix.lower().lstrip(".")
        if filename_extension == "jpeg":
            filename_extension = "jpg"
        if filename_extension != extension:
            raise FileExtensionMismatchException()

        if file.size is not None and file.size > MAX_FILE_SIZE:
            raise FileTooLargeException()

        data = file.file.read(MAX_FILE_SIZE + 1)

        if not data:
            raise EmptyFileException()

        if len(data) > MAX_FILE_SIZE:
            raise FileTooLargeException()

        if not is_valid_file_content(data, extension):
            raise InvalidFileContentException()

        key = f"materials/{uuid4().hex}/{filename}"

        if len(key.encode("utf-8")) > 1024:
            raise FilenameTooLongException()

        try:
            with self.journal.create(settings.S3_BUCKET, key) as job:
                try:
                    self.storage.upload_file(key, data, file.content_type)
                except FileStorageError:
                    job.update(state='upload_uncertain', last_error_code='upload_failed')
                    logger.error("Ошибка загрузки материала в S3; задание %s сохранено", job.data['id'])
                    raise FileUploadFailedException() from None
                job.update(state='uploaded')
                # Keep the OS lock through the complete registration transaction.
                yield {
                    "bucket": settings.S3_BUCKET,
                    "storage_key": key,
                    "original_filename": filename,
                    "mime_type": file.content_type,
                    "size_bytes": len(data),
                    "uploaded_by_id": user_id,
                }, job
                try:
                    job.complete()
                except JournalError:
                    # Registration succeeded. A stale job will find the live
                    # metadata and finish without deleting the object.
                    logger.error("Не удалось завершить задание %s", job.data['id'])
        except JournalError:
            logger.error("Журнал восстановления файлов недоступен")
            raise FileJournalUnavailableException() from None

    def _remove_uploaded_file(self, job):
        try:
            result = FileCleanupService(
                self.files.repository, self.storage, settings.S3_BUCKET, self.journal,
            ).process(job)
            if result == 'deferred':
                logger.warning("Компенсационная очистка отложена: %s", job.data['id'])
        except JournalError:
            logger.error("Задание компенсационной очистки сохранено: %s", job.data['id'])

    def create_material(self, launch_id: int, user_id: int, title: str, description: str | None, file: MaterialUpload, section_id: int | None = None, kind: MaterialKind = MaterialKind.other, position: int = 0):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            raise LaunchNotFoundException()

        if section_id is not None:
            section = self.sections.get_section_by_id(section_id, user_id)
            if section is None or section["launch_id"] != launch_id:
                raise SectionNotFoundInLaunchException()

        with self._upload_file(user_id, file) as (file_data, job):
            try:
                material = self.repository.create_material(launch_id, {
                    "title": title,
                    "description": description,
                    "section_id": section_id,
                    "kind": kind,
                    "position": position,
                }, file_data)
            except SQLAlchemyError:
                logger.exception("Ошибка сохранения материала в БД")
                self._remove_uploaded_file(job)
                raise MaterialSaveFailedException() from None

        return {"success": True, **material}

    def get_all_materials(self, launch_id: int, user_id: int):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            raise LaunchNotFoundException()

        return {"success": True, "data": self.repository.get_all_materials(launch_id, user_id)}

    def get_material_by_id(self, material_id: int, user_id: int):
        material = self.repository.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundException()

        return {"success": True, **material}

    def edit_material(self, material_id: int, user_id: int, data: UpdateMaterialRequest):
        changes = data.model_dump(exclude_unset=True)
        try:
            with self.repository.transaction():
                material = self.repository.lock_material(material_id, user_id)
                if material is None:
                    raise MaterialNotFoundException()
                if data.section_id is not None:
                    section = self.sections.get_section_by_id(data.section_id, user_id)
                    if section is None or section["launch_id"] != material["launch_id"]:
                        raise SectionNotFoundInLaunchException()
                if "section_id" in changes and changes["section_id"] != material["section_id"]:
                    section_ids = self.notes.get_material_section_ids(material_id)
                    if any(section_id != changes["section_id"] for section_id in section_ids):
                        raise MaterialSectionHasNotesException()
                material = self.repository.edit_material(material_id, user_id, changes)
        except IntegrityError:
            raise RelatedDataChangedException()
        return {"success": True, **material}

    def replace_file(self, material_id: int, user_id: int, file: MaterialUpload):
        if self.repository.get_material_by_id(material_id, user_id) is None:
            raise MaterialNotFoundException()

        with self._upload_file(user_id, file) as (file_data, job):
            try:
                material = self.repository.replace_file(material_id, user_id, file_data)
            except SQLAlchemyError:
                logger.exception("Ошибка замены файла в БД")
                self._remove_uploaded_file(job)
                raise MaterialFileReplacementFailedException() from None

            if material is None:
                self._remove_uploaded_file(job)
                raise MaterialNotFoundException()

        previous_file_id = material.pop("previous_stored_file_id")
        try:
            self.files.delete_file_if_unused(previous_file_id, user_id)
        except AppException:
            raise ReplacedFileCleanupFailedException(previous_file_id) from None

        return {"success": True, **material}

    def copy_material(self, material_id: int, user_id: int, data: CopyMaterialRequest):
        material = self.repository.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundException()

        source = self.launches.get_launch_by_id(material["launch_id"], user_id)
        target = self.launches.get_launch_by_id(data.launch_id, user_id)
        if source is None or target is None:
            raise LaunchNotFoundException()
        if source["module_id"] != target["module_id"]:
            raise CrossModuleCopyException()
        if source["id"] == target["id"]:
            raise SameLaunchCopyException()

        if data.section_id is not None:
            section = self.sections.get_section_by_id(data.section_id, user_id)
            if section is None or section["launch_id"] != target["id"]:
                raise SectionNotFoundInTargetLaunchException()

        try:
            copy = self.repository.copy_material(material_id, user_id, data.model_dump())
        except FileUnavailableError:
            raise FileUnavailableForCopyException()
        except IntegrityError:
            raise RelatedDataChangedException()

        if copy is None:
            raise MaterialNotFoundException()

        return {"success": True, **copy}

    def delete_material(self, material_id: int, user_id: int):
        try:
            material = self.repository.delete_material(material_id, user_id)
        except IntegrityError:
            raise RelatedDataChangedException()
        except SQLAlchemyError:
            logger.exception("Ошибка удаления материала из БД")
            raise MaterialDeletionFailedException()

        if material is None:
            raise MaterialNotFoundException()

        file_id = material["stored_file_id"]
        try:
            self.files.delete_file_if_unused(file_id, user_id)
        except AppException:
            raise DeletedMaterialCleanupFailedException(file_id) from None

        return {"success": True, "message": "Материал удалён"}
