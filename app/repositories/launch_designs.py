from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_db
from models.launch_designs import LaunchDesign
from models.launches import Launch
from models.modules import Module
from repositories.transactions import transaction


class LaunchDesignRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(design: LaunchDesign):
        return {"launch_id": design.launch_id, "template_version": design.template_version,
                "data": design.data, "created_at": design.created_at, "updated_at": design.updated_at}

    def _owned_launch(self, launch_id: int, user_id: int):
        return select(Launch).join(Module, Launch.module_id == Module.id).where(
            Launch.id == launch_id, Module.owner_id == user_id,
        )

    def get_design(self, launch_id: int, user_id: int):
        if self.db.scalar(self._owned_launch(launch_id, user_id)) is None:
            return None
        design = self.db.get(LaunchDesign, launch_id)
        if design is None:
            return {"launch_id": launch_id, "template_version": 1, "data": {},
                    "created_at": None, "updated_at": None}
        return self._to_dict(design)

    def replace_design(self, launch_id: int, user_id: int, template_version: int, data: dict):
        with transaction(self.db):
            # Serializes replacements, including concurrent creation of a missing record.
            launch = self.db.scalar(self._owned_launch(launch_id, user_id).with_for_update(of=Launch))
            if launch is None:
                return None
            design = self.db.scalar(select(LaunchDesign).where(LaunchDesign.launch_id == launch_id).execution_options(populate_existing=True))
            if design is None:
                design = LaunchDesign(launch_id=launch_id)
                self.db.add(design)
            design.template_version = template_version
            design.data = data
            self.db.flush()
            self.db.refresh(design)
            result = self._to_dict(design)
        return result
