import uuid
from datetime import datetime

from pydantic import BaseModel


class PresignUploadRequest(BaseModel):
    file_type: str  # e.g. "image", "pdf", "docx"
    content_type: str  # MIME type, e.g. "application/pdf"


class PresignUploadResponse(BaseModel):
    upload_url: str
    storage_key: str
    expires_in: int


class DeliverableCreateRequest(BaseModel):
    storage_key: str | None = None
    file_type: str | None = None
    external_link: str | None = None
    note: str | None = None


class DeliverableResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    storage_key: str
    file_type: str | None
    external_link: str | None
    note: str | None
    created_at: datetime

    class Config:
        from_attributes = True
