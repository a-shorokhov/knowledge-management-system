from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from core.exceptions import (
    LaunchNotFoundException,
    MaterialNotFoundInLaunchException,
    MaterialSectionMismatchException,
    NoteNotFoundException,
    RelatedDataChangedException,
    SectionNotFoundInLaunchException,
)
from repositories.launches import LaunchRepository
from repositories.notes import NoteRepository
from repositories.materials import MaterialRepository
from repositories.sections import SectionRepository
from schemas.notes import CreateNoteRequest, UpdateNoteRequest


class NoteService:
    def __init__(
        self,
        repository: NoteRepository = Depends(),
        launches: LaunchRepository = Depends(),
        materials: MaterialRepository = Depends(),
        sections: SectionRepository = Depends(),
    ):
        self.repository = repository
        self.launches = launches
        self.materials = materials
        self.sections = sections

    def _check_links(self, launch_id: int, user_id: int, material_id: int | None, section_id: int | None):
        if section_id is not None:
            section = self.sections.get_section_by_id(section_id, user_id)
            if section is None or section["launch_id"] != launch_id:
                raise SectionNotFoundInLaunchException()
        if material_id is not None:
            material = self.materials.get_material_by_id(material_id, user_id)
            if material is None or material["launch_id"] != launch_id:
                raise MaterialNotFoundInLaunchException()
            if section_id is not None and material["section_id"] != section_id:
                raise MaterialSectionMismatchException()
        return {"success": True}

    def create_note(self, launch_id: int, user_id: int, data: CreateNoteRequest):
        try:
            with self.repository.transaction():
                if not self.repository.lock_launch(launch_id) or self.launches.get_launch_by_id(launch_id, user_id) is None:
                    raise LaunchNotFoundException()
                self._check_links(launch_id, user_id, data.material_id, data.section_id)
                note = self.repository.create_note(launch_id, {**data.model_dump(), "author_id": user_id})
        except IntegrityError:
            raise RelatedDataChangedException()
        return {"success": True, **note}

    def get_all_notes(self, launch_id: int, user_id: int):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            raise LaunchNotFoundException()

        return {"success": True, "data": self.repository.get_all_notes(launch_id, user_id)}

    def get_note_by_id(self, note_id: int, user_id: int):
        note = self.repository.get_note_by_id(note_id, user_id)
        if note is None:
            raise NoteNotFoundException()

        return {"success": True, **note}

    def edit_note(self, note_id: int, user_id: int, data: UpdateNoteRequest):
        changes = data.model_dump(exclude_unset=True)
        try:
            with self.repository.transaction():
                note = self.repository.lock_note(note_id, user_id)
                if note is None:
                    raise NoteNotFoundException()
                self._check_links(note["launch_id"], user_id, changes.get("material_id", note["material_id"]), changes.get("section_id", note["section_id"]))
                note = self.repository.edit_note(note_id, user_id, changes)
        except IntegrityError:
            raise RelatedDataChangedException()
        return {"success": True, **note}

    def delete_note(self, note_id: int, user_id: int):
        if not self.repository.delete_note(note_id, user_id):
            raise NoteNotFoundException()

        return {"success": True, "message": "Заметка удалена"}
