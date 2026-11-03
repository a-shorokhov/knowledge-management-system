from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import get_db
from models.launches import Launch
from models.materials import Material
from models.modules import Module
from models.stored_files import StoredFile
from repositories.stored_files import FileUnavailableError, StoredFileRepository
from repositories.launches import lock_launches
from repositories.transactions import transaction


class MaterialRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(material: Material):
        return {
            "id": material.id,
            "launch_id": material.launch_id,
            "section_id": material.section_id,
            "stored_file_id": material.stored_file_id,
            "title": material.title,
            "description": material.description,
            "kind": material.kind,
            "position": material.position,
            "copied_from_material_id": material.copied_from_material_id,
            "created_at": material.created_at,
            "updated_at": material.updated_at,
        }

    def _get_owned_material(self, material_id: int, user_id: int):
        return self.db.scalar(
            select(Material)
            .join(Launch, Material.launch_id == Launch.id)
            .join(Module, Launch.module_id == Module.id)
            .where(Material.id == material_id, Module.owner_id == user_id)
            .execution_options(populate_existing=True)
        )

    def create_material(self, launch_id: int, data: dict, file_data: dict):
        try:
            lock_launches(self.db, [launch_id])
            stored_file = StoredFile(**file_data)
            self.db.add(stored_file)
            self.db.flush()
            material = Material(launch_id=launch_id, stored_file_id=stored_file.id, **data)
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
            .where(Material.launch_id == launch_id, Module.owner_id == user_id)
            .order_by(Material.position, Material.id)
        ).all()
        return {material.id: self._to_dict(material) for material in materials}

    def get_material_by_id(self, material_id: int, user_id: int):
        material = self._get_owned_material(material_id, user_id)
        return self._to_dict(material) if material is not None else None

    def transaction(self):
        return transaction(self.db)

    def lock_material(self, material_id: int, user_id: int):
        material = self._get_owned_material(material_id, user_id)
        if material is None or not lock_launches(self.db, [material.launch_id]):
            return None
        self.db.refresh(material, with_for_update=True)
        return self._to_dict(material)

    def edit_material(self, material_id: int, user_id: int, data: dict):
        material = self._get_owned_material(material_id, user_id)
        if material is None:
            return None
        for key, value in data.items():
            setattr(material, key, value)
        self.db.flush()
        self.db.refresh(material)
        return self._to_dict(material)

    def replace_file(self, material_id: int, user_id: int, file_data: dict):
        material = self._get_owned_material(material_id, user_id)
        if material is None:
            return None

        try:
            lock_launches(self.db, [material.launch_id])
            self.db.refresh(material, with_for_update=True)
            previous_file_id = material.stored_file_id
            files = StoredFileRepository(self.db)
            files.lock_files([previous_file_id])
            stored_file = StoredFile(**file_data)
            self.db.add(stored_file)
            self.db.flush()
            material.stored_file_id = stored_file.id
            self.db.flush()
            self.db.refresh(material)
            result = self._to_dict(material)
            result["previous_stored_file_id"] = previous_file_id
            files.mark_unused_files([previous_file_id])
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return result

    def copy_material(self, material_id: int, user_id: int, data: dict):
        source = self._get_owned_material(material_id, user_id)
        if source is None:
            return None

        try:
            launch_ids = sorted({source.launch_id, data["launch_id"]})
            if len(lock_launches(self.db, launch_ids)) != len(launch_ids):
                return None
            source = self._get_owned_material(material_id, user_id)
            if source is None:
                return None
            files = StoredFileRepository(self.db).lock_files([source.stored_file_id])
            if not files or files[0].deletion_pending:
                raise FileUnavailableError
            material = Material(
                stored_file_id=source.stored_file_id,
                title=source.title,
                description=source.description,
                kind=source.kind,
                copied_from_material_id=source.id,
                **data,
            )
            self.db.add(material)
            self.db.flush()
            self.db.refresh(material)
            result = self._to_dict(material)
            self.db.commit()
        except (SQLAlchemyError, FileUnavailableError):
            self.db.rollback()
            raise

        return result

    def delete_material(self, material_id: int, user_id: int):
        material = self._get_owned_material(material_id, user_id)
        if material is None:
            return None

        try:
            lock_launches(self.db, [material.launch_id])
            self.db.refresh(material, with_for_update=True)
            result = self._to_dict(material)
            files = StoredFileRepository(self.db)
            files.lock_files([result["stored_file_id"]])
            self.db.delete(material)
            self.db.flush()
            files.mark_unused_files([result["stored_file_id"]])
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return result
