from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.database import get_db
from models.notes import Note
from models.modules import Module
from models.launches import Launch
from repositories.launches import lock_launches
from repositories.transactions import transaction


class NoteRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(note: Note):
        return {
            "id": note.id,
            "launch_id": note.launch_id,
            "material_id": note.material_id,
            "section_id": note.section_id,
            "author_id": note.author_id,
            "title": note.title,
            "content": note.content,
            "problem_or_practice": note.problem_or_practice,
            "cause": note.cause,
            "proposed_solution": note.proposed_solution,
            "priority": note.priority,
            "status": note.status,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
        }

    def _get_owned_note(self, note_id: int, user_id: int):
        return self.db.scalar(
            select(Note)
            .join(Launch, Note.launch_id == Launch.id)
            .join(Module, Launch.module_id == Module.id)
            .where(Note.id == note_id, Module.owner_id == user_id)
        )

    def transaction(self):
        return transaction(self.db)

    def lock_launch(self, launch_id: int):
        return bool(lock_launches(self.db, [launch_id]))

    def lock_note(self, note_id: int, user_id: int):
        note = self._get_owned_note(note_id, user_id)
        if note is None or not self.lock_launch(note.launch_id):
            return None
        self.db.refresh(note, with_for_update=True)
        return self._to_dict(note)

    def get_material_section_ids(self, material_id: int):
        return list(self.db.scalars(select(Note.section_id).where(Note.material_id == material_id, Note.section_id.is_not(None))).all())

    def create_note(self, launch_id: int, data: dict):
        note = Note(launch_id=launch_id, **data)
        self.db.add(note)
        self.db.flush()
        self.db.refresh(note)
        return self._to_dict(note)

    def get_all_notes(self, launch_id: int, user_id: int):
        notes = self.db.scalars(
            select(Note)
            .join(Launch, Note.launch_id == Launch.id)
            .join(Module, Launch.module_id == Module.id)
            .where(
                Note.launch_id == launch_id,
                Module.owner_id == user_id,
            )
            .order_by(Note.id)
        ).all()

        return {note.id: self._to_dict(note) for note in notes}

    def get_note_by_id(self, note_id: int, user_id: int):
        note = self._get_owned_note(note_id, user_id)
        return self._to_dict(note) if note is not None else None

    def edit_note(self, note_id: int, user_id: int, data: dict):
        note = self._get_owned_note(note_id, user_id)
        if note is None:
            return None
        for key, value in data.items():
            setattr(note, key, value)
        self.db.flush()
        self.db.refresh(note)
        return self._to_dict(note)

    def delete_note(self, note_id: int, user_id: int):
        note = self._get_owned_note(note_id, user_id)

        if note is None:
            return False

        try:
            self.db.delete(note)
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

        return True
