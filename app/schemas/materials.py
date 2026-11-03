from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.enums import MaterialKind


@dataclass
class MaterialUpload:
    file: BinaryIO
    filename: str | None
    content_type: str | None
    size: int | None


class UpdateMaterialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    section_id: int | None = Field(default=None, ge=1)
    kind: MaterialKind | None = None
    position: int | None = Field(default=None, ge=0)

    @field_validator("title", "kind", "position")
    @classmethod
    def fields_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Поле не может быть пустым")
        return value


class CopyMaterialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    launch_id: int = Field(ge=1)
    section_id: int | None = Field(default=None, ge=1)
    position: int = Field(default=0, ge=0)


class MaterialResponse(BaseModel):
    id: int
    launch_id: int
    section_id: int | None
    stored_file_id: int
    title: str
    description: str | None
    kind: MaterialKind
    position: int
    copied_from_material_id: int | None
    created_at: datetime
    updated_at: datetime
