from fastapi import Depends

from repositories.modules import ModuleRepository
from schemas.modules import CreateModuleRequest, UpdateModuleRequest


class ModuleService:
    def __init__(self, repository: ModuleRepository = Depends()):
        self.repository = repository

    def create_module(self, user_id: int, data: CreateModuleRequest):
        module = self.repository.create_module(user_id, data.model_dump())

        return {
            "success": True,
            "id": module["id"],
            "user_id": module["user_id"],
            "title": module["title"],
            "description": module["description"],
        }

    def get_all_modules(self, user_id: int):
        return self.repository.get_all_modules(user_id)

    def get_module_by_id(self, module_id: int, user_id: int):
        module = self.repository.get_module_by_id(module_id, user_id)

        if module is None:
            return {
                "success": False,
                "message": "Модуль не найден",
            }

        return {
            "success": True,
            "id": module["id"],
            "user_id": module["user_id"],
            "title": module["title"],
            "description": module["description"],
        }

    def edit_module(self, module_id: int, user_id: int, data: UpdateModuleRequest):
        module = self.repository.edit_module(
            module_id, user_id, data.model_dump(exclude_unset=True)
        )

        if module is None:
            return {
                "success": False,
                "message": "Модуль не найден",
            }

        return {
            "success": True,
            "id": module["id"],
            "user_id": module["user_id"],
            "title": module["title"],
            "description": module["description"],
        }

    def delete_module(self, module_id: int, user_id: int):
        if not self.repository.delete_module(module_id, user_id):
            return {
                "success": False,
                "message": "Модуль не найден",
            }

        return {
            "success": True,
            "message": "Модуль удалён",
        }