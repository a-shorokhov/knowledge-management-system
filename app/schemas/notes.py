from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.enums import NotePriority, NoteStatus


class NoteTextFields(BaseModel):
    problem_or_practice: str | None = None
    cause: str | None = None
    proposed_solution: str | None = None


class CreateNoteRequest(NoteTextFields):
    model_config = ConfigDict(extra="forbid")

    priority: NotePriority = NotePriority.medium
    status: NoteStatus = NoteStatus.open

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, description="Что произошло")
    material_id: int | None = Field(default=None, ge=1)
    section_id: int | None = Field(default=None, ge=1)


class UpdateNoteRequest(NoteTextFields):
    model_config = ConfigDict(extra="forbid")

    priority: NotePriority | None = None
    status: NoteStatus | None = None

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    material_id: int | None = Field(default=None, ge=1)
    section_id: int | None = Field(default=None, ge=1)

    @field_validator("title", "content", "priority", "status")
    @classmethod
    def fields_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Заметка не может быть пустой")
        return value


class NoteResponse(NoteTextFields):
    priority: NotePriority
    status: NoteStatus
    id: int
    launch_id: int
    material_id: int | None
    section_id: int | None
    author_id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
