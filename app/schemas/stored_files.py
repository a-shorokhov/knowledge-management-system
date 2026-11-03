from datetime import datetime

from pydantic import BaseModel

from models.enums import FileIndexStatus


class StoredFileResponse(BaseModel):
    id: int
    original_filename: str
    mime_type: str
    size_bytes: int
    uploaded_by_id: int
    deletion_pending: bool
    indexing_status: FileIndexStatus
    indexing_error_code: str | None
    indexed_at: datetime | None
    created_at: datetime


class DownloadResponse(BaseModel):
    url: str
    expires_in: int
