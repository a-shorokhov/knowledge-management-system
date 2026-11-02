from datetime import datetime

from pydantic import BaseModel


class MaterialResponse(BaseModel):
    id: int
    launch_id: int
    title: str
    description: str | None
    original_filename: str
    created_at: datetime