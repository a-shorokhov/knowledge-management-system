from fastapi import Depends

from repositories.launches import LaunchRepository
from repositories.notes import NoteRepository
from schemas.notes import CreateNoteRequest, UpdateNoteRequest


class NoteService:
    def __init__(
        self,
        repository: NoteRepository = Depends(),
        launches: LaunchRepository = Depends(),
    ):
        self.repository = repository
        self.launches = launches

    def create_note(self, launch_id: int, user_id: int, data: CreateNoteRequest):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            return {
                "success": False,
                "message": "Запуск не найден",
            }

        note = self.repository.create_note(launch_id, data.model_dump())

        return {
            "success": True,
            "id": note["id"],
            "launch_id": note["launch_id"],
            "title": note["title"],
            "content": note["content"],
            "created_at": note["created_at"],
        }

    def get_all_notes(self, launch_id: int, user_id: int):
        if self.launches.get_launch_by_id(launch_id, user_id) is None:
            return {
                "success": False,
                "message": "Запуск не найден",
            }

        return {
            "success": True,
            "data": self.repository.get_all_notes(launch_id, user_id),
        }

    def get_note_by_id(self, note_id: int, user_id: int):
        note = self.repository.get_note_by_id(note_id, user_id)

        if note is None:
            return {
                "success": False,
                "message": "Заметка не найдена",
            }

        return {
            "success": True,
            "id": note["id"],
            "launch_id": note["launch_id"],
            "title": note["title"],
            "content": note["content"],
            "created_at": note["created_at"],
        }

    def edit_note(self, note_id: int, user_id: int, data: UpdateNoteRequest):
        note = self.repository.edit_note(
            note_id, user_id, data.model_dump(exclude_unset=True)
        )

        if note is None:
            return {
                "success": False,
                "message": "Заметка не найдена",
            }

        return {
            "success": True,
            "id": note["id"],
            "launch_id": note["launch_id"],
            "title": note["title"],
            "content": note["content"],
            "created_at": note["created_at"],
        }

    def delete_note(self, note_id: int, user_id: int):
        if not self.repository.delete_note(note_id, user_id):
            return {
                "success": False,
                "message": "Заметка не найдена",
            }

        return {
            "success": True,
            "message": "Заметка удалена",
        }