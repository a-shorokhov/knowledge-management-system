from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import get_db
from models.launches import Launch
from models.materials import Material
from models.modules import Module


class MaterialRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(material: Material):
        return {
            "id": material.id,
            "launch_id": material.launch_id,
            "title": material.title,
            "description": material.description,
            "original_filename": material.original_filename,
            "storage_key": material.storage_key,
            "created_at": material.created_at,
        }

    def _get_owned_material(self, material_id: int, user_id: int):
        return self.db.scalar(
            select(Material)
            .join(Launch, Material.launch_id == Launch.id)
            .join(Module, Launch.module_id == Module.id)
            .where(
                Material.id == material_id,
                Module.user_id == user_id,
            )
        )

    def create_material(self, launch_id: int, data: dict):
        material = Material(launch_id=launch_id, **data)

        try:
            self.db.add(material)
            self.db.flush()
            self.db.refresh(material)
            result = self._to_dict(material)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return result

    def get_all_materials(self, launch_id: int, user_id: int):
        materials = self.db.scalars(
            select(Material)
            .join(Launch, Material.launch_id == Launch.id)
            .join(Module, Launch.module_id == Module.id)
            .where(
                Material.launch_id == launch_id,
                Module.user_id == user_id,
            )
            .order_by(Material.id)
        ).all()

        return {material.id: self._to_dict(material) for material in materials}

    def get_material_by_id(self, material_id: int, user_id: int):
        material = self._get_owned_material(material_id, user_id)

        return self._to_dict(material) if material is not None else None

    def delete_material(self, material_id: int, user_id: int):
        material = self._get_owned_material(material_id, user_id)

        if material is None:
            return False

        try:
            self.db.delete(material)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return True