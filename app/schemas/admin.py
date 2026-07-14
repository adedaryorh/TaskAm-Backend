import uuid
from datetime import datetime

from pydantic import BaseModel


class StudentAdminResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    school: str | None
    is_verified: bool
    full_name: str
    phone_number: str

    class Config:
        from_attributes = True


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    before_state: dict | None
    after_state: dict | None
    created_at: datetime

    class Config:
        from_attributes = True
