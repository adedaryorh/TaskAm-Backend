import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.base import TaskStatus, RequestSource, ServiceCategory


class TaskResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    title: str | None
    category: str | None
    requirements: str | None
    complexity: str | None
    suggested_payout: float | None
    final_payout: float | None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    requester_user_id: uuid.UUID | None = None
    request_source: RequestSource = RequestSource.TASKAM
    external_request_id: str | None = None
    service_category: ServiceCategory | None = None
    farm_location: dict | None = None
    agricultural_details: dict | None = None
    requested_start_at: datetime | None = None
    logistics_handoff_reference: str | None = None

    class Config:
        from_attributes = True


class TaskClaimResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    student_id: uuid.UUID | None
    provider_user_id: uuid.UUID
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
