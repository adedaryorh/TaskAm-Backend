import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.base import TaskStatus, PaymentStatus
from app.models.payment import Payment
from app.models.task import Task
from app.services import opay_service, paystack_service
from app.services.task_service import transition_task
from app.models.task_claim import TaskClaim
from app.models.user import Student, ProviderProfile

SUPPORTED_PROVIDERS = {"OPAY", "PAYSTACK"}


def initiate_payment(
    db: Session,
    task: Task,
    merchant_id: uuid.UUID,
    merchant_email: str | None = None,
    provider: str | None = None,
) -> Payment:
    if task.status != TaskStatus.CLAIMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task must be CLAIMED before funding (status={task.status.value})",
        )
    if task.final_payout is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task has no final payout amount set")

    existing = db.query(Payment).filter(Payment.task_id == task.id).first()
    if existing is not None:
        return existing

    provider = (provider or settings.default_payment_provider).upper()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported provider: {provider}")

    reference = opay_service.new_payment_reference(task.id)  # same reference scheme works for both providers

    if provider == "OPAY":
        order = opay_service.create_checkout_order(reference, task.final_payout)
        provider_reference = order["order_id"]
        checkout_url = order["checkout_url"]
    else:  # PAYSTACK
        order = paystack_service.initialize_transaction(
            reference, task.final_payout, email=merchant_email or f"{merchant_id}@taskam.placeholder"
        )
        provider_reference = order["reference"]
        checkout_url = order["checkout_url"]

    payment = Payment(
        task_id=task.id,
        merchant_id=merchant_id,
        amount=task.final_payout,
        provider=provider,
        provider_reference=provider_reference,
        checkout_url=checkout_url,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def _parse_opay_event(raw_payload: dict) -> tuple[str | None, bool, bool]:
    """Returns (provider_reference, is_success, is_failure)."""
    reference = raw_payload.get("orderNo") or raw_payload.get("reference")
    event_status = (raw_payload.get("status") or "").upper()
    return reference, event_status in ("SUCCESS", "SUCCESSFUL", "PAID"), event_status in ("FAILED", "CANCELLED")


def _parse_paystack_event(raw_payload: dict) -> tuple[str | None, bool, bool]:
    """
    Paystack webhook shape: {"event": "charge.success", "data": {"reference": ..., "status": "success", ...}}
    """
    data = raw_payload.get("data", {})
    reference = data.get("reference")
    event = raw_payload.get("event", "")
    data_status = (data.get("status") or "").lower()
    is_success = event == "charge.success" or data_status == "success"
    is_failure = event in ("charge.failed",) or data_status in ("failed", "abandoned")
    return reference, is_success, is_failure


def handle_payment_webhook(db: Session, provider: str, raw_payload: dict) -> None:
    """
    Called only after webhook_service.record_webhook_event has confirmed
    this is a new event and signature verification has already passed
    (both happen in the router before this is called).
    """
    if provider == "OPAY":
        provider_reference, is_success, is_failure = _parse_opay_event(raw_payload)
    elif provider == "PAYSTACK":
        provider_reference, is_success, is_failure = _parse_paystack_event(raw_payload)
    else:
        return

    if not provider_reference:
        return

    payment = (
        db.query(Payment)
        .filter(Payment.provider == provider, Payment.provider_reference == provider_reference)
        .first()
    )
    if payment is None:
        return

    payment.raw_webhook_payload = raw_payload

    if is_success:
        payment.status = PaymentStatus.FUNDED
        task = db.get(Task, payment.task_id)
        if task is not None and task.status == TaskStatus.CLAIMED:
            transition_task(db, task, TaskStatus.FUNDED)
            db.commit()

            from app.models.task_claim import TaskClaim
            from app.models.user import Student
            from app.services.notification_service import notify

            claim = db.query(TaskClaim).filter(TaskClaim.task_id == task.id, TaskClaim.status == "ACTIVE").first()
            if claim is not None:
                notify(
                    db,
                    user_id=claim.provider_user_id,
                    task_id=task.id,
                    channel="WHATSAPP",
                    event_type="TASK_FUNDED",
                    body=f'"{task.title}" is funded — you can start work now.',
                )
    elif is_failure:
        payment.status = PaymentStatus.FAILED

    db.commit()


def release_payment(db: Session, task: Task) -> Payment:
    if not settings.payment_settlement_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Payment settlement is disabled")
    payment = db.query(Payment).filter(Payment.task_id == task.id).first()
    claim = db.query(TaskClaim).filter(TaskClaim.task_id == task.id, TaskClaim.status == "ACTIVE").first()
    if payment is None or payment.status != PaymentStatus.FUNDED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task has no funded payment")
    if claim is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task has no active claim")
    payout_profile = db.get(Student, claim.student_id) if claim.student_id else db.query(ProviderProfile).filter(
        ProviderProfile.user_id == claim.provider_user_id
    ).first()
    if not payout_profile or not payout_profile.payout_account_number or not payout_profile.payout_bank_code or not payout_profile.payout_account_name:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Provider has not configured a payout account")
    reference = f"payout-{payment.id}"
    try:
        if payment.provider == "PAYSTACK":
            recipient = payout_profile.payout_recipient_code
            if not recipient:
                recipient = paystack_service.create_transfer_recipient(
                    payout_profile.payout_account_name, payout_profile.payout_account_number, payout_profile.payout_bank_code
                )
                payout_profile.payout_recipient_code = recipient
            settlement_reference = paystack_service.initiate_transfer(reference, float(payment.amount), recipient, f"TaskAm payout {task.id}")
        else:
            settlement_reference = opay_service.initiate_transfer(
                reference, float(payment.amount), payout_profile.payout_account_number,
                payout_profile.payout_bank_code, payout_profile.payout_account_name,
            )
    except Exception as exc:
        payment.settlement_error = str(exc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Provider rejected payout") from exc
    payment.settlement_reference = settlement_reference
    payment.settlement_error = None
    payment.status = PaymentStatus.RELEASED
    claim.status = "COMPLETED"
    return payment


def refund_payment(db: Session, task: Task) -> Payment:
    if not settings.payment_settlement_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Payment settlement is disabled")
    payment = db.query(Payment).filter(Payment.task_id == task.id).first()
    if payment is None or payment.status != PaymentStatus.FUNDED or not payment.provider_reference:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task has no refundable payment")
    reference = f"refund-{payment.id}"
    try:
        if payment.provider == "PAYSTACK":
            settlement_reference = paystack_service.initiate_refund(payment.provider_reference, float(payment.amount))
        else:
            settlement_reference = opay_service.initiate_refund(payment.provider_reference, float(payment.amount), reference)
    except Exception as exc:
        payment.settlement_error = str(exc)
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Provider rejected refund") from exc
    payment.settlement_reference = settlement_reference
    payment.settlement_error = None
    payment.status = PaymentStatus.REFUNDED
    return payment
