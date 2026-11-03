from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import get_db
from models.materials import Material
from repositories.launches import lock_launches
from repositories.stored_files import StoredFileRepository
from models.sections import RunSection
from models.modules import Module
from models.launches import Launch


class SectionRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(section: RunSection):
        return {
            "id": section.id,
            "launch_id": section.launch_id,
            "title": section.title,
            "description": section.description,
            "position": section.position,
        }

    def _get_owned_section(self, section_id: int, user_id: int):
        return self.db.scalar(
            select(RunSection)
            .join(Launch, RunSection.launch_id == Launch.id)
            .join(Module, Launch.module_id == Module.id)
            .where(RunSection.id == section_id, Module.owner_id == user_id)
        )

    def create_section(self, launch_id: int, data: dict):
        section = RunSection(launch_id=launch_id, **data)

        try:
            self.db.add(section)
            self.db.flush()
            self.db.refresh(section)
            result = self._to_dict(section)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return result

    def get_all_sections(self, launch_id: int, user_id: int):
        sections = self.db.scalars(
            select(RunSection)
            .join(Launch, RunSection.launch_id == Launch.id)
            .join(Module, Launch.module_id == Module.id)
            .where(
                RunSection.launch_id == launch_id,
                Module.owner_id == user_id,
            )
            .order_by(RunSection.position, RunSection.id)
        ).all()

        return {section.id: self._to_dict(section) for section in sections}

    def get_section_by_id(self, section_id: int, user_id: int):
        section = self._get_owned_section(section_id, user_id)
        return self._to_dict(section) if section is not None else None

    def edit_section(self, section_id: int, user_id: int, data: dict):
        section = self._get_owned_section(section_id, user_id)

        if section is None:
            return None

        try:
            for key, value in data.items():
                setattr(section, key, value)
            self.db.flush()
            self.db.refresh(section)
            result = self._to_dict(section)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return result

    def delete_section(self, section_id: int, user_id: int):
        section = self._get_owned_section(section_id, user_id)
        if section is None:
            return None

        try:
            lock_launches(self.db, [section.launch_id])
            self.db.refresh(section, with_for_update=True)
            file_ids = list(self.db.scalars(select(Material.stored_file_id).where(Material.section_id == section_id).distinct().order_by(Material.stored_file_id)).all())
            files = StoredFileRepository(self.db)
            files.lock_files(file_ids)
            self.db.delete(section)
            self.db.flush()
            files.mark_unused_files(file_ids)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return file_ids
