from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GenerateRetrospectiveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    compared_to_launch_id: int | None = Field(default=None, strict=True, gt=0)


class AIRetrospectiveResponse(BaseModel):
    id: int
    launch_id: int
    compared_to_launch_id: int | None
    generated_by_id: int
    content: str
    created_at: datetime
