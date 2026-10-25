from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_db
from models.launches import Launch
from models.modules import Module


class LaunchRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(launch: Launch):
        return {
            "id": launch.id,
            "module_id": launch.module_id,
            "year": launch.year,
            "title": launch.title,
            "description": launch.description,
        }

    def _get_owned_launch(self, launch_id: int, user_id: int):
        return self.db.scalar(
            select(Launch)
            .join(Module, Launch.module_id == Module.id)
            .where(
                Launch.id == launch_id,
                Module.user_id == user_id,
            )
        )

    def create_launch(self, module_id: int, data: dict):
        launch = Launch(module_id=module_id, **data)

        self.db.add(launch)
        self.db.commit()
        self.db.refresh(launch)

        return self._to_dict(launch)

    def get_all_launches(self, module_id: int, user_id: int):
        launches = self.db.scalars(
            select(Launch)
            .join(Module, Launch.module_id == Module.id)
            .where(
                Launch.module_id == module_id,
                Module.user_id == user_id,
            )
            .order_by(Launch.id)
        ).all()

        return {launch.id: self._to_dict(launch) for launch in launches}

    def get_launch_by_id(self, launch_id: int, user_id: int):
        launch = self._get_owned_launch(launch_id, user_id)

        return self._to_dict(launch) if launch is not None else None

    def edit_launch(self, launch_id: int, user_id: int, data: dict):
        launch = self._get_owned_launch(launch_id, user_id)

        if launch is None:
            return None

        if data:
            for key, value in data.items():
                setattr(launch, key, value)

            self.db.commit()
            self.db.refresh(launch)

        return self._to_dict(launch)

    def delete_launch(self, launch_id: int, user_id: int):
        launch = self._get_owned_launch(launch_id, user_id)

        if launch is None:
            return False

        self.db.delete(launch)
        self.db.commit()

        return True