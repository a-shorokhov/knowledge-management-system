from fastapi import APIRouter, Depends

from core.depends import get_current_user
from schemas.notes import CreateNoteRequest, UpdateNoteRequest, NoteResponse
from services.notes import NoteService


router = APIRouter(tags=["notes"])


@router.post("/launches/{launch_id}/notes", status_code=201, response_model=NoteResponse)
def create_note(
    launch_id: int,
    data: CreateNoteRequest,
    service: NoteService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.create_note(launch_id, current_user["id"], data)

    return result


@router.get("/launches/{launch_id}/notes", response_model=dict[int, NoteResponse])
def get_notes(
    launch_id: int,
    service: NoteService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_all_notes(launch_id, current_user["id"])

    return result["data"]


@router.get("/notes/{note_id}", response_model=NoteResponse)
def get_note_by_id(
    note_id: int,
    service: NoteService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_note_by_id(note_id, current_user["id"])

    return result


@router.patch("/notes/{note_id}", response_model=NoteResponse)
def update_note(
    note_id: int,
    data: UpdateNoteRequest,
    service: NoteService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.edit_note(note_id, current_user["id"], data)

    return result


@router.delete("/notes/{note_id}")
def delete_note(
    note_id: int,
    service: NoteService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.delete_note(note_id, current_user["id"])

    return result
