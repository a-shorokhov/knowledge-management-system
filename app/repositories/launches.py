from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import get_db
from models.launches import Launch
from models.modules import Module
from models.sections import RunSection
from models.materials import Material
from repositories.stored_files import FileUnavailableError, StoredFileRepository
from repositories.transactions import transaction


def lock_launches(db: Session, launch_ids: list[int]):
    return db.scalars(
        select(Launch)
        .where(Launch.id.in_(launch_ids))
        .order_by(Launch.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()


class LaunchRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(launch: Launch):
        return {
            "id": launch.id,
            "module_id": launch.module_id,
            "title": launch.title,
            "description": launch.description,
            "year": launch.year,
            "semester": launch.semester,
            "status": launch.status,
            "copied_from_launch_id": launch.copied_from_launch_id,
            "created_at": launch.created_at,
            "updated_at": launch.updated_at,
        }

    def _get_owned_launch(self, launch_id: int, user_id: int):
        return self.db.scalar(
            select(Launch)
            .join(Module, Launch.module_id == Module.id)
            .where(Launch.id == launch_id, Module.owner_id == user_id)
        )

    def create_launch(self, module_id: int, data: dict):
        launch = Launch(module_id=module_id, **data)

        try:
            self.db.add(launch)
            self.db.flush()
            self.db.refresh(launch)
            result = self._to_dict(launch)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return result

    def get_all_launches(self, module_id: int, user_id: int):
        launches = self.db.scalars(
            select(Launch)
            .join(Module, Launch.module_id == Module.id)
            .where(
                Launch.module_id == module_id,
                Module.owner_id == user_id,
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

        try:
            for key, value in data.items():
                setattr(launch, key, value)
            self.db.flush()
            self.db.refresh(launch)
            result = self._to_dict(launch)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return result

    def delete_launch(self, launch_id: int, user_id: int):
        launch = self._get_owned_launch(launch_id, user_id)
        if launch is None:
            return None

        try:
            if not lock_launches(self.db, [launch_id]):
                return None
            file_ids = list(self.db.scalars(select(Material.stored_file_id).where(Material.launch_id == launch_id).distinct().order_by(Material.stored_file_id)).all())
            files = StoredFileRepository(self.db)
            files.lock_files(file_ids)
            self.db.delete(launch)
            self.db.flush()
            files.mark_unused_files(file_ids)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return file_ids

    def transaction(self):
        return transaction(self.db)

    def get_copy_source(self, launch_id: int, user_id: int):
        source = self._get_owned_launch(launch_id, user_id)
        if source is None:
            return None
        self.db.scalar(select(Module).where(Module.id == source.module_id).with_for_update())
        if not lock_launches(self.db, [launch_id]):
            return None
        return self._to_dict(source)

    def get_copy_sections(self, launch_id: int):
        sections = self.db.scalars(select(RunSection).where(RunSection.launch_id == launch_id).order_by(RunSection.id)).all()
        return [{"id": section.id, "title": section.title, "description": section.description, "position": section.position} for section in sections]

    def get_copy_materials(self, launch_id: int):
        materials = self.db.scalars(select(Material).where(Material.launch_id == launch_id).order_by(Material.id).execution_options(populate_existing=True)).all()
        file_ids = sorted({material.stored_file_id for material in materials})
        files = StoredFileRepository(self.db).lock_files(file_ids)
        if len(files) != len(file_ids) or any(stored_file.deletion_pending for stored_file in files):
            raise FileUnavailableError
        return [{"id": material.id, "section_id": material.section_id, "stored_file_id": material.stored_file_id, "title": material.title, "description": material.description, "kind": material.kind, "position": material.position} for material in materials]

    def save_launch_copy(self, data: dict, sections: dict[int, dict], materials: list[dict]):
        launch = Launch(**data)
        self.db.add(launch)
        self.db.flush()
        section_ids = {}
        for source_id, section_data in sections.items():
            section = RunSection(launch_id=launch.id, **section_data)
            self.db.add(section)
            self.db.flush()
            section_ids[source_id] = section.id
        for material_data in materials:
            values = {**material_data, "section_id": section_ids.get(material_data["section_id"])}
            self.db.add(Material(launch_id=launch.id, **values))
        self.db.flush()
        self.db.refresh(launch)
        return self._to_dict(launch)
