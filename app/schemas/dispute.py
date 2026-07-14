import uuid
from datetime import datetime

from pydantic import BaseModel


class DisputeCreateRequest(BaseModel):
    reason: str


class DisputeResolveRequest(BaseModel):
    resolution: str  # "RESOLVED_MERCHANT" | "RESOLVED_STUDENT"
    resolution_note: str | None = None


class DisputeResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    raised_by_user_id: uuid.UUID
    reason: str
    status: str
    resolution_note: str | None
    created_at: datetime

    class Config:
        from_attributes = True
