from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from core.exceptions import LaunchNotFoundException, RelatedDataChangedException
from repositories.launch_reflections import LaunchReflectionRepository
from schemas.launch_reflections import ReplaceLaunchReflectionRequest


class LaunchReflectionService:
    def __init__(self, repository: LaunchReflectionRepository = Depends()):
        self.repository = repository

    def get_reflection(self, launch_id: int, user_id: int):
        reflection = self.repository.get_reflection(launch_id, user_id)
        if reflection is None:
            raise LaunchNotFoundException()
        return reflection

    def replace_reflection(self, launch_id: int, user_id: int, data: ReplaceLaunchReflectionRequest):
        try:
            # All four fields, including omitted ones as null: full replacement.
            reflection = self.repository.replace_reflection(launch_id, user_id, data.model_dump())
        except IntegrityError:
            raise RelatedDataChangedException() from None
        if reflection is None:
            raise LaunchNotFoundException()
        return reflection
