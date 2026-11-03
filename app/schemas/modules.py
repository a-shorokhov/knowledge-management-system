from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateModuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str


class UpdateModuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None

    @field_validator("title", "description")
    @classmethod
    def fields_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Поле не может быть пустым")
        return value


class ModuleResponse(BaseModel):
    id: int
    owner_id: int
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
