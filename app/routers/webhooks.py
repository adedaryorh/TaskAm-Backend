import hashlib
import logging
import hmac
import time

from fastapi import APIRouter, Depends, Query, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.base import WebhookSource
from app.services import whatsapp_client, opay_service, paystack_service
from app.services.webhook_service import record_webhook_event, finish_webhook_event
from app.services.payment_service import handle_payment_webhook
from app.services.queue import enqueue
from app.core.rate_limit import enforce_webhook_rate_limit
from app.core.config import settings
from app.core.service_auth import webhook_signature
from app.schemas.integration import PlatformEventEnvelope
from app.models.task import Task
from app.services.integration_service import enqueue_farmsense_envelope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

WHATSAPP_QUEUE = "whatsapp_messages"


@router.get("/whatsapp")
def verify_whatsapp_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    challenge = whatsapp_client.verify_webhook_challenge(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")
    # Meta expects the raw challenge string back, not JSON.
    return int(challenge) if challenge.isdigit() else challenge


def _verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Verify Meta's X-Hub-Signature-256 header (HMAC-SHA256 of the raw body
    keyed with the app secret). Rejects everything when no secret is set."""
    if not settings.whatsapp_app_secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    supplied = signature_header.removeprefix("sha256=")
    expected = hmac.new(
        settings.whatsapp_app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, supplied)


@router.post("/whatsapp", status_code=status.HTTP_200_OK)
async def receive_whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    if not _verify_meta_signature(raw_body, request.headers.get("x-hub-signature-256")):
        logger.warning("Rejected WhatsApp webhook with missing/invalid X-Hub-Signature-256")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    payload = await request.json()
    # DB/Redis work is synchronous — keep it off the event loop.
    return await run_in_threadpool(_process_whatsapp_webhook, request, db, payload)


def _process_whatsapp_webhook(request: Request, db: Session, payload: dict):
    enforce_webhook_rate_limit(request)
    messages = whatsapp_client.parse_webhook_payload(payload)

    for msg in messages:
        if not msg.message_id:
            continue

        is_new = record_webhook_event(db, WebhookSource.WHATSAPP, msg.message_id, payload)
        if not is_new:
            logger.info("Duplicate WhatsApp message %s — skipping", msg.message_id)
            continue

        # Hand off to the background worker so this endpoint returns fast
        # (Meta expects a quick 200; heavy work — media download, AI calls,
        # DB writes — happens out-of-band).
        try:
            enqueue(
                WHATSAPP_QUEUE,
                job_type="process_whatsapp_message",
                payload={
                    "message_id": msg.message_id, "from_wa_id": msg.from_wa_id,
                    "timestamp": msg.timestamp, "message_type": msg.message_type,
                    "text_body": msg.text_body, "media_id": msg.media_id,
                },
            )
            finish_webhook_event(db, WebhookSource.WHATSAPP, msg.message_id)
        except Exception as exc:
            finish_webhook_event(db, WebhookSource.WHATSAPP, msg.message_id, exc)
            raise

    # Always 200 quickly, even for empty/status-update payloads, or Meta
    # will retry and eventually disable the webhook.
    return {"status": "received"}


@router.post("/opay", status_code=status.HTTP_200_OK)
async def receive_opay_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("signature") or request.headers.get("Signature")

    if not opay_service.verify_webhook_signature(raw_body, signature):
        logger.warning("Rejected OPay webhook with invalid signature")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()
    return await run_in_threadpool(_process_opay_webhook, request, db, payload)


def _process_opay_webhook(request: Request, db: Session, payload: dict):
    enforce_webhook_rate_limit(request)
    external_id = payload.get("orderNo") or payload.get("reference") or payload.get("transactionId")
    if not external_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing order reference")

    is_new = record_webhook_event(db, WebhookSource.OPAY, external_id, payload)
    if not is_new:
        logger.info("Duplicate OPay webhook %s — skipping", external_id)
        return {"status": "already processed"}

    try:
        handle_payment_webhook(db, "OPAY", payload)
        finish_webhook_event(db, WebhookSource.OPAY, external_id)
    except Exception as exc:
        finish_webhook_event(db, WebhookSource.OPAY, external_id, exc)
        raise
    return {"status": "received"}


@router.post("/paystack", status_code=status.HTTP_200_OK)
async def receive_paystack_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")

    if not paystack_service.verify_webhook_signature(raw_body, signature):
        logger.warning("Rejected Paystack webhook with invalid signature")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()
    return await run_in_threadpool(_process_paystack_webhook, request, db, payload)


def _process_paystack_webhook(request: Request, db: Session, payload: dict):
    enforce_webhook_rate_limit(request)
    external_id = payload.get("data", {}).get("reference")
    if not external_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing transaction reference")

    is_new = record_webhook_event(db, WebhookSource.PAYSTACK, external_id, payload)
    if not is_new:
        logger.info("Duplicate Paystack webhook %s — skipping", external_id)
        return {"status": "already processed"}

    try:
        handle_payment_webhook(db, "PAYSTACK", payload)
        finish_webhook_event(db, WebhookSource.PAYSTACK, external_id)
    except Exception as exc:
        finish_webhook_event(db, WebhookSource.PAYSTACK, external_id, exc)
        raise
    return {"status": "received"}


@router.post("/logistics", status_code=status.HTTP_200_OK)
async def receive_logistics_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    timestamp = request.headers.get("x-logistics-timestamp", "")
    supplied = request.headers.get("x-logistics-signature", "").removeprefix("sha256=")
    try:
        fresh = abs(time.time() - int(timestamp)) <= settings.service_auth_max_skew_seconds
    except ValueError:
        fresh = False
    expected = webhook_signature(settings.logistics_webhook_secret, timestamp, raw_body)
    if not settings.logistics_webhook_secret or not fresh or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid logistics webhook signature")
    envelope = PlatformEventEnvelope.model_validate_json(raw_body)
    if envelope.source != "logistics" or not envelope.logistics_delivery_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid logistics event envelope")
    return await run_in_threadpool(_process_logistics_webhook, request, db, envelope)


def _process_logistics_webhook(request: Request, db: Session, envelope: PlatformEventEnvelope):
    enforce_webhook_rate_limit(request)
    is_new = record_webhook_event(db, WebhookSource.LOGISTICS, envelope.event_id, envelope.model_dump(mode="json"))
    if not is_new:
        return {"status": "already processed", "event_id": envelope.event_id}
    task = db.query(Task).filter(Task.logistics_delivery_id == envelope.logistics_delivery_id).first()
    if task is None:
        finish_webhook_event(db, WebhookSource.LOGISTICS, envelope.event_id, ValueError("Unknown delivery"))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    if envelope.marketplace_request_id and envelope.marketplace_request_id != task.marketplace_request_id:
        finish_webhook_event(db, WebhookSource.LOGISTICS, envelope.event_id, ValueError("ID mismatch"))
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Event identifiers do not match")
    enqueue_farmsense_envelope(db, task, envelope.model_dump(mode="json"))
    finish_webhook_event(db, WebhookSource.LOGISTICS, envelope.event_id)
    return {"status": "received", "event_id": envelope.event_id}
