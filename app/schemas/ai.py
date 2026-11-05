from typing import Literal

from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated


class AskRequest(BaseModel):
    module_id: int = Field(gt=0)
    launch_id: int | None = Field(default=None, gt=0)
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class SourceResponse(BaseModel):
    source_id: str
    material_id: int
    launch_id: int
    title: str
    page_number: int | None = None
    slide_number: int | None = None
    sheet_name: str | None = None
    cell_range: str | None = None
    chunk_index: int
    download_path: str
    excerpt: str


class AskResponse(BaseModel):
    status: Literal['ok', 'no_sources']
    answer: str
    sources: list[SourceResponse]
