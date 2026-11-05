from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_db
from models.launch_reflections import LaunchReflection
from models.launches import Launch
from models.modules import Module
from repositories.transactions import transaction


class LaunchReflectionRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(reflection: LaunchReflection):
        return {
            "launch_id": reflection.launch_id,
            "what_went_well": reflection.what_went_well,
            "recurring_problems": reflection.recurring_problems,
            "materials_to_update": reflection.materials_to_update,
            "decisions_to_keep": reflection.decisions_to_keep,
            "created_at": reflection.created_at,
            "updated_at": reflection.updated_at,
        }

    def _owned_launch(self, launch_id: int, user_id: int):
        return select(Launch).join(Module, Launch.module_id == Module.id).where(
            Launch.id == launch_id, Module.owner_id == user_id,
        )

    def get_reflection(self, launch_id: int, user_id: int):
        if self.db.scalar(self._owned_launch(launch_id, user_id)) is None:
            return None
        reflection = self.db.get(LaunchReflection, launch_id)
        if reflection is None:
            return {"launch_id": launch_id, "what_went_well": None, "recurring_problems": None,
                    "materials_to_update": None, "decisions_to_keep": None,
                    "created_at": None, "updated_at": None}
        return self._to_dict(reflection)

    def replace_reflection(self, launch_id: int, user_id: int, data: dict):
        with transaction(self.db):
            # Serialize PUTs on the launch, including creation of the first record.
            launch = self.db.scalar(self._owned_launch(launch_id, user_id).with_for_update(of=Launch))
            if launch is None:
                return None
            reflection = self.db.scalar(
                select(LaunchReflection).where(LaunchReflection.launch_id == launch_id)
                .execution_options(populate_existing=True)
            )
            if reflection is None:
                reflection = LaunchReflection(launch_id=launch_id)
                self.db.add(reflection)
            for key, value in data.items():
                setattr(reflection, key, value)
            self.db.flush()
            self.db.refresh(reflection)
            result = self._to_dict(reflection)
        return result
