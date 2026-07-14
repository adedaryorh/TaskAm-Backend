import uuid
from datetime import datetime

from pydantic import BaseModel


class PaymentResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    amount: float
    currency: str
    provider: str
    provider_reference: str | None
    checkout_url: str | None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
