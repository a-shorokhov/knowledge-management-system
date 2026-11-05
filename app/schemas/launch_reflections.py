from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReplaceLaunchReflectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what_went_well: str | None = Field(default=None, description="Что прошло хорошо")
    recurring_problems: str | None = Field(default=None, description="Повторявшиеся проблемы")
    materials_to_update: str | None = Field(default=None, description="Материалы, которые нужно обновить")
    decisions_to_keep: str | None = Field(default=None, description="Решения, которые стоит сохранить")


class LaunchReflectionResponse(ReplaceLaunchReflectionRequest):
    launch_id: int
    created_at: datetime | None
    updated_at: datetime | None
