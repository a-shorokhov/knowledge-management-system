from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateSectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    position: int = Field(default=0, ge=0)


class UpdateSectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    position: int | None = Field(default=None, ge=0)

    @field_validator("title", "position")
    @classmethod
    def fields_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Поле не может быть пустым")
        return value


class SectionResponse(BaseModel):
    id: int
    launch_id: int
    title: str
    description: str | None
    position: int
