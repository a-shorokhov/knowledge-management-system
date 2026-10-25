from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=1, le=9999)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None


class UpdateLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int | None = Field(default=None, ge=1, le=9999)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None

    @field_validator("year")
    @classmethod
    def year_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Год запуска не может быть пустым")

        return value


class LaunchResponse(BaseModel):
    id: int
    module_id: int
    year: int
    title: str | None
    description: str | None