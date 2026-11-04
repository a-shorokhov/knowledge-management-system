from fastapi import Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.exceptions import (
    ContentDeletionFailedException,
    FileCleanupFailedException,
    FileUnavailableForCopyException,
    LaunchNotFoundException,
    ModuleNotFoundException,
    RelatedDataChangedException,
)
from repositories.launches import LaunchRepository
from repositories.modules import ModuleRepository
from repositories.stored_files import FileUnavailableError
from services.stored_files import StoredFileService
from schemas.launches import CreateLaunchRequest, UpdateLaunchRequest


class LaunchService:
    def __init__(
        self,
        repository: LaunchRepository = Depends(),
        modules: ModuleRepository = Depends(),
        files: StoredFileService = Depends(),
    ):
        self.repository = repository
        self.files = files
        self.modules = modules

    def create_launch(self, module_id: int, user_id: int, data: CreateLaunchRequest):
        if self.modules.get_module_by_id(module_id, user_id) is None:
            raise ModuleNotFoundException()

        try:
            launch = self.repository.create_launch(module_id, data.model_dump())
        except IntegrityError:
            raise RelatedDataChangedException()

        return {"success": True, **launch}

    def get_all_launches(self, module_id: int, user_id: int):
        if self.modules.get_module_by_id(module_id, user_id) is None:
            raise ModuleNotFoundException()

        return {"success": True, "data": self.repository.get_all_launches(module_id, user_id)}

    def get_launch_by_id(self, launch_id: int, user_id: int):
        launch = self.repository.get_launch_by_id(launch_id, user_id)
        if launch is None:
            raise LaunchNotFoundException()

        return {"success": True, **launch}

    def edit_launch(self, launch_id: int, user_id: int, data: UpdateLaunchRequest):
        try:
            launch = self.repository.edit_launch(launch_id, user_id, data.model_dump(exclude_unset=True))
        except IntegrityError:
            raise RelatedDataChangedException()

        if launch is None:
            raise LaunchNotFoundException()

        return {"success": True, **launch}

    def delete_launch(self, launch_id: int, user_id: int):
        try:
            file_ids = self.repository.delete_launch(launch_id, user_id)
        except IntegrityError:
            raise RelatedDataChangedException()
        except SQLAlchemyError:
            raise ContentDeletionFailedException()

        if file_ids is None:
            raise LaunchNotFoundException()

        try:
            self.files.delete_unused_files(file_ids, user_id)
        except FileCleanupFailedException as exc:
            raise FileCleanupFailedException(
                exc.detail["ErrorContext"]["file_ids"],
                prefix="Запуск и его содержимое удалены. ",
            ) from None

        return {"success": True, "message": "Запуск и его содержимое удалены"}

    def copy_launch(self, launch_id: int, user_id: int, data: CreateLaunchRequest):
        try:
            with self.repository.transaction():
                source = self.repository.get_copy_source(launch_id, user_id)
                if source is None:
                    raise LaunchNotFoundException()
                source_sections = self.repository.get_copy_sections(launch_id)
                source_materials = self.repository.get_copy_materials(launch_id)
                sections = {
                    section["id"]: {"title": section["title"], "description": section["description"], "position": section["position"]}
                    for section in source_sections
                }
                materials = [{
                    "section_id": material["section_id"],
                    "stored_file_id": material["stored_file_id"],
                    "title": material["title"],
                    "description": material["description"],
                    "kind": material["kind"],
                    "position": material["position"],
                    "copied_from_material_id": material["id"],
                } for material in source_materials]
                launch = self.repository.save_launch_copy({
                    **data.model_dump(),
                    "module_id": source["module_id"],
                    "copied_from_launch_id": source["id"],
                }, sections, materials)
        except FileUnavailableError:
            raise FileUnavailableForCopyException()
        except IntegrityError:
            raise RelatedDataChangedException()

        if launch is None:
            raise LaunchNotFoundException()

        return {"success": True, **launch}
