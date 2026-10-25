from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateModuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    description: str | None = None


class UpdateModuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    description: str | None = None

    @field_validator("title")
    @classmethod
    def title_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Название модуля не может быть пустым")

        return value


class ModuleResponse(BaseModel):
    id: int
    user_id: int
    title: str
    description: str | None