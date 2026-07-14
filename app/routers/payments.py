import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.db.session import get_db
from app.models.base import UserRole
from app.models.user import User, Merchant
from app.schemas.payment import PaymentResponse
from app.services.payment_service import initiate_payment
from app.routers.tasks import _get_owned_task

router = APIRouter(prefix="/tasks", tags=["payments"])


class InitiatePaymentRequest(BaseModel):
    provider: str | None = None  # "OPAY" | "PAYSTACK" — defaults to settings.default_payment_provider
    email: str | None = None  # required by Paystack; ignored by OPay


@router.post("/{task_id}/payments/initiate", response_model=PaymentResponse, status_code=201)
def initiate_payment_endpoint(
    task_id: uuid.UUID,
    payload: InitiatePaymentRequest = InitiatePaymentRequest(),
    current_user: User = Depends(require_roles(UserRole.MERCHANT)),
    db: Session = Depends(get_db),
):
    task = _get_owned_task(db, task_id, current_user)
    merchant = db.query(Merchant).filter(Merchant.user_id == current_user.id).first()
    return initiate_payment(
        db,
        task,
        merchant_id=merchant.id,
        merchant_email=payload.email,
        provider=payload.provider,
    )
