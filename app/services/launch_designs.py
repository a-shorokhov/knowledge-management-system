from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from core.exceptions import LaunchNotFoundException, RelatedDataChangedException
from repositories.launch_designs import LaunchDesignRepository
from schemas.launch_designs import LaunchDesignData, ReplaceLaunchDesignRequest


class LaunchDesignService:
    def __init__(self, repository: LaunchDesignRepository = Depends()):
        self.repository = repository

    def get_template(self):
        return {"template_version": 1, "description": "Фиксированная форма запуска. В черновике все поля необязательны; неизвестные поля запрещены. Тематический план хранится отдельным материалом категории plan.",
                "data_schema": LaunchDesignData.model_json_schema()}

    def get_design(self, launch_id: int, user_id: int):
        design = self.repository.get_design(launch_id, user_id)
        if design is None:
            raise LaunchNotFoundException()
        return design

    def replace_design(self, launch_id: int, user_id: int, data: ReplaceLaunchDesignRequest):
        try:
            design = self.repository.replace_design(launch_id, user_id, data.template_version, data.data.model_dump(exclude_unset=True))
        except IntegrityError:
            raise RelatedDataChangedException() from None
        if design is None:
            raise LaunchNotFoundException()
        return design
