from fastapi import Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core.exceptions import (
    ContentDeletionFailedException,
    FileCleanupFailedException,
    LaunchNotFoundException,
    RelatedDataChangedException,
    SectionNotFoundException,
)
from repositories.sections import SectionRepository
from repositories.launches import LaunchRepository
from services.stored_files import StoredFileService
from schemas.sections import CreateSectionRequest, UpdateSectionRequest


class SectionService:
    def __init__(
        self,
        repository: SectionRepository = Depends(),
        launches: LaunchRepository = Depends(),
        files: StoredFileService = Depends(),
    ):
        self.repository = repository
        self.files = files
        self.launches = launches

    def create_section(self, launch_id: int, user_id: int, data: CreateSectionRequest):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            raise LaunchNotFoundException()

        try:
            section = self.repository.create_section(launch_id, data.model_dump())
        except IntegrityError:
            raise RelatedDataChangedException()

        return {"success": True, **section}

    def get_all_sections(self, launch_id: int, user_id: int):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            raise LaunchNotFoundException()

        return {"success": True, "data": self.repository.get_all_sections(launch_id, user_id)}

    def get_section_by_id(self, section_id: int, user_id: int):
        section = self.repository.get_section_by_id(section_id, user_id)
        if section is None:
            raise SectionNotFoundException()

        return {"success": True, **section}

    def edit_section(self, section_id: int, user_id: int, data: UpdateSectionRequest):
        try:
            section = self.repository.edit_section(section_id, user_id, data.model_dump(exclude_unset=True))
        except IntegrityError:
            raise RelatedDataChangedException()

        if section is None:
            raise SectionNotFoundException()

        return {"success": True, **section}

    def delete_section(self, section_id: int, user_id: int):
        try:
            file_ids = self.repository.delete_section(section_id, user_id)
        except IntegrityError:
            raise RelatedDataChangedException()
        except SQLAlchemyError:
            raise ContentDeletionFailedException()

        if file_ids is None:
            raise SectionNotFoundException()

        try:
            self.files.delete_unused_files(file_ids, user_id)
        except FileCleanupFailedException as exc:
            raise FileCleanupFailedException(
                exc.detail["ErrorContext"]["file_ids"],
                prefix="Раздел и его содержимое удалены. ",
            ) from None

        return {"success": True, "message": "Раздел и его содержимое удалены"}
