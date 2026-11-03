from fastapi import Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.exceptions import (
    ContentDeletionFailedException,
    FileCleanupFailedException,
    ModuleNotFoundException,
    RelatedDataChangedException,
)
from repositories.modules import ModuleRepository
from services.stored_files import StoredFileService
from schemas.modules import CreateModuleRequest, UpdateModuleRequest


class ModuleService:
    def __init__(self, repository: ModuleRepository = Depends(), files: StoredFileService = Depends()):
        self.repository = repository
        self.files = files

    def create_module(self, user_id: int, data: CreateModuleRequest):
        try:
            module = self.repository.create_module(user_id, data.model_dump())
        except IntegrityError:
            raise RelatedDataChangedException()

        return {"success": True, **module}

    def get_all_modules(self, user_id: int):
        return {"success": True, "data": self.repository.get_all_modules(user_id)}

    def get_module_by_id(self, module_id: int, user_id: int):
        module = self.repository.get_module_by_id(module_id, user_id)
        if module is None:
            raise ModuleNotFoundException()

        return {"success": True, **module}

    def edit_module(self, module_id: int, user_id: int, data: UpdateModuleRequest):
        try:
            module = self.repository.edit_module(module_id, user_id, data.model_dump(exclude_unset=True))
        except IntegrityError:
            raise RelatedDataChangedException()

        if module is None:
            raise ModuleNotFoundException()

        return {"success": True, **module}

    def delete_module(self, module_id: int, user_id: int):
        try:
            file_ids = self.repository.delete_module(module_id, user_id)
        except IntegrityError:
            raise RelatedDataChangedException()
        except SQLAlchemyError:
            raise ContentDeletionFailedException()

        if file_ids is None:
            raise ModuleNotFoundException()

        try:
            self.files.delete_unused_files(file_ids, user_id)
        except FileCleanupFailedException as exc:
            raise FileCleanupFailedException(
                exc.detail["ErrorContext"]["file_ids"],
                prefix="Модуль и его содержимое удалены. ",
            ) from None

        return {"success": True, "message": "Модуль и его содержимое удалены"}
