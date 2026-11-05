from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.enums import RunStatus


class LaunchDetails(BaseModel):
    starts_on: date | None = None
    ends_on: date | None = None
    participant_count: int | None = Field(default=None, ge=0, strict=True)
    changes_summary: str | None = None
    changes_reason: str | None = None

    @model_validator(mode="after")
    def check_dates(self):
        if self.starts_on is not None and self.ends_on is not None and self.ends_on < self.starts_on:
            raise ValueError("Дата окончания не может быть раньше даты начала")
        return self


class CreateLaunchRequest(LaunchDetails):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    year: int = Field(ge=1, le=9999)
    semester: str = Field(min_length=1, max_length=32)
    status: RunStatus = RunStatus.draft


class UpdateLaunchRequest(LaunchDetails):
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


class LaunchResponse(LaunchDetails):
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
