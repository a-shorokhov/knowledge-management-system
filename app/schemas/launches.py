from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.enums import RunStatus


class CreateLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str
    year: int = Field(ge=1, le=9999)
    semester: str = Field(min_length=1, max_length=32)
    status: RunStatus = RunStatus.draft


class UpdateLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    year: int | None = Field(default=None, ge=1, le=9999)
    semester: str | None = Field(default=None, min_length=1, max_length=32)
    status: RunStatus | None = None

    @field_validator("title", "description", "year", "semester", "status")
    @classmethod
    def fields_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Поле не может быть пустым")
        return value


class LaunchResponse(BaseModel):
    id: int
    module_id: int
    title: str
    description: str
    year: int
    semester: str
    status: RunStatus
    copied_from_launch_id: int | None
    created_at: datetime
    updated_at: datetime
