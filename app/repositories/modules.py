from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_db
from models.modules import Module


class ModuleRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(module: Module):
        return {
            "id": module.id,
            "user_id": module.user_id,
            "title": module.title,
            "description": module.description,
        }

    def _get_owned_module(self, module_id: int, user_id: int):
        return self.db.scalar(
            select(Module).where(
                Module.id == module_id,
                Module.user_id == user_id,
            )
        )

    def create_module(self, user_id: int, data: dict):
        module = Module(user_id=user_id, **data)

        self.db.add(module)
        self.db.commit()
        self.db.refresh(module)

        return self._to_dict(module)

    def get_all_modules(self, user_id: int):
        modules = self.db.scalars(
            select(Module)
            .where(Module.user_id == user_id)
            .order_by(Module.id)
        ).all()

        return {module.id: self._to_dict(module) for module in modules}

    def get_module_by_id(self, module_id: int, user_id: int):
        module = self._get_owned_module(module_id, user_id)

        return self._to_dict(module) if module is not None else None

    def edit_module(self, module_id: int, user_id: int, data: dict):
        module = self._get_owned_module(module_id, user_id)

        if module is None:
            return None

        if data:
            for key, value in data.items():
                setattr(module, key, value)

            self.db.commit()
            self.db.refresh(module)

        return self._to_dict(module)

    def delete_module(self, module_id: int, user_id: int):
        module = self._get_owned_module(module_id, user_id)

        if module is None:
            return False

        self.db.delete(module)
        self.db.commit()

        return True