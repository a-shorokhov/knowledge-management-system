from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import get_db
from models.materials import Material
from repositories.launches import lock_launches
from repositories.stored_files import StoredFileRepository
from models.modules import Module
from models.launches import Launch


class ModuleRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(module: Module):
        return {
            "id": module.id,
            "owner_id": module.owner_id,
            "title": module.title,
            "description": module.description,
            "created_at": module.created_at,
            "updated_at": module.updated_at,
        }

    def _get_owned_module(self, module_id: int, user_id: int):
        return self.db.scalar(
            select(Module)
            .where(Module.id == module_id, Module.owner_id == user_id)
        )

    def create_module(self, user_id: int, data: dict):
        module = Module(owner_id=user_id, **data)

        try:
            self.db.add(module)
            self.db.flush()
            self.db.refresh(module)
            result = self._to_dict(module)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return result

    def get_all_modules(self, user_id: int):
        modules = self.db.scalars(
            select(Module)
            .where(
                Module.owner_id == user_id,
            )
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

        try:
            for key, value in data.items():
                setattr(module, key, value)
            self.db.flush()
            self.db.refresh(module)
            result = self._to_dict(module)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return result

    def delete_module(self, module_id: int, user_id: int):
        module = self._get_owned_module(module_id, user_id)
        if module is None:
            return None

        try:
            self.db.refresh(module, with_for_update=True)
            launch_ids = list(self.db.scalars(select(Launch.id).where(Launch.module_id == module_id).order_by(Launch.id)).all())
            lock_launches(self.db, launch_ids)
            file_ids = list(self.db.scalars(select(Material.stored_file_id).join(Launch, Material.launch_id == Launch.id).where(Launch.module_id == module_id).distinct().order_by(Material.stored_file_id)).all())
            files = StoredFileRepository(self.db)
            files.lock_files(file_ids)
            self.db.delete(module)
            self.db.flush()
            files.mark_unused_files(file_ids)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return file_ids
