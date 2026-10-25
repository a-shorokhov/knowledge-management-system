from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_db
from models.launches import Launch
from models.modules import Module
from models.notes import Note


class NoteRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(note: Note):
        return {
            "id": note.id,
            "launch_id": note.launch_id,
            "title": note.title,
            "content": note.content,
            "created_at": note.created_at,
        }

    def _get_owned_note(self, note_id: int, user_id: int):
        return self.db.scalar(
            select(Note)
            .join(Launch, Note.launch_id == Launch.id)
            .join(Module, Launch.module_id == Module.id)
            .where(
                Note.id == note_id,
                Module.user_id == user_id,
            )
        )

    def create_note(self, launch_id: int, data: dict):
        note = Note(launch_id=launch_id, **data)

        self.db.add(note)
        self.db.commit()
        self.db.refresh(note)

        return self._to_dict(note)

    def get_all_notes(self, launch_id: int, user_id: int):
        notes = self.db.scalars(
            select(Note)
            .join(Launch, Note.launch_id == Launch.id)
            .join(Module, Launch.module_id == Module.id)
            .where(
                Note.launch_id == launch_id,
                Module.user_id == user_id,
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

        if data:
            for key, value in data.items():
                setattr(note, key, value)

            self.db.commit()
            self.db.refresh(note)

        return self._to_dict(note)

    def delete_note(self, note_id: int, user_id: int):
        note = self._get_owned_note(note_id, user_id)

        if note is None:
            return False

        self.db.delete(note)
        self.db.commit()

        return True