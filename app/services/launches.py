from fastapi import Depends

from repositories.launches import LaunchRepository
from repositories.modules import ModuleRepository
from schemas.launches import CreateLaunchRequest, UpdateLaunchRequest


class LaunchService:
    def __init__(
        self,
        repository: LaunchRepository = Depends(),
        modules: ModuleRepository = Depends(),
    ):
        self.repository = repository
        self.modules = modules

    def create_launch(self, module_id: int, user_id: int, data: CreateLaunchRequest):
        if self.modules.get_module_by_id(module_id, user_id) is None:
            return {
                "success": False,
                "message": "Модуль не найден",
            }

        launch = self.repository.create_launch(module_id, data.model_dump())

        return {
            "success": True,
            "id": launch["id"],
            "module_id": launch["module_id"],
            "year": launch["year"],
            "title": launch["title"],
            "description": launch["description"],
        }

    def get_all_launches(self, module_id: int, user_id: int):
        if self.modules.get_module_by_id(module_id, user_id) is None:
            return {
                "success": False,
                "message": "Модуль не найден",
            }

        return {
            "success": True,
            "data": self.repository.get_all_launches(module_id, user_id),
        }

    def get_launch_by_id(self, launch_id: int, user_id: int):
        launch = self.repository.get_launch_by_id(launch_id, user_id)

        if launch is None:
            return {
                "success": False,
                "message": "Запуск не найден",
            }

        return {
            "success": True,
            "id": launch["id"],
            "module_id": launch["module_id"],
            "year": launch["year"],
            "title": launch["title"],
            "description": launch["description"],
        }

    def edit_launch(self, launch_id: int, user_id: int, data: UpdateLaunchRequest):
        launch = self.repository.edit_launch(
            launch_id, user_id, data.model_dump(exclude_unset=True)
        )

        if launch is None:
            return {
                "success": False,
                "message": "Запуск не найден",
            }

        return {
            "success": True,
            "id": launch["id"],
            "module_id": launch["module_id"],
            "year": launch["year"],
            "title": launch["title"],
            "description": launch["description"],
        }

    def delete_launch(self, launch_id: int, user_id: int):
        if not self.repository.delete_launch(launch_id, user_id):
            return {
                "success": False,
                "message": "Запуск не найден",
            }

        return {
            "success": True,
            "message": "Запуск удалён",
        }