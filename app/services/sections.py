from fastapi import Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
            return {"success": False, "message": "Запуск не найден"}

        try:
            section = self.repository.create_section(launch_id, data.model_dump())
        except IntegrityError:
            return {"success": False, "message": "Связанные данные изменились, повторите запрос", "status_code": 409}

        return {"success": True, **section}

    def get_all_sections(self, launch_id: int, user_id: int):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            return {"success": False, "message": "Запуск не найден"}

        return {"success": True, "data": self.repository.get_all_sections(launch_id, user_id)}

    def get_section_by_id(self, section_id: int, user_id: int):
        section = self.repository.get_section_by_id(section_id, user_id)
        if section is None:
            return {"success": False, "message": "Раздел не найден"}

        return {"success": True, **section}

    def edit_section(self, section_id: int, user_id: int, data: UpdateSectionRequest):
        try:
            section = self.repository.edit_section(section_id, user_id, data.model_dump(exclude_unset=True))
        except IntegrityError:
            return {"success": False, "message": "Связанные данные изменились, повторите запрос", "status_code": 409}

        if section is None:
            return {"success": False, "message": "Раздел не найден"}

        return {"success": True, **section}

    def delete_section(self, section_id: int, user_id: int):
        try:
            file_ids = self.repository.delete_section(section_id, user_id)
        except IntegrityError:
            return {"success": False, "message": "Связанные данные изменились, повторите запрос", "status_code": 409}
        except SQLAlchemyError:
            return {"success": False, "message": "Не удалось удалить содержимое из базы данных", "status_code": 503}

        if file_ids is None:
            return {"success": False, "message": "Раздел не найден"}

        cleanup = self.files.delete_unused_files(file_ids, user_id)
        if not cleanup["success"]:
            return {**cleanup, "message": "Раздел и его содержимое удалены. " + cleanup["message"]}

        return {"success": True, "message": "Раздел и его содержимое удалены"}
