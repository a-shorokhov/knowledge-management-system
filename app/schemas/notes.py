from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class UpdateNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1)

    @field_validator("title", "content")
    @classmethod
    def fields_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Заметка не может быть пустой")

        return value


class NoteResponse(BaseModel):
    id: int
    launch_id: int
    title: str
    content: str
    created_at: datetime