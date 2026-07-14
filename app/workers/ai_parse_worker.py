"""
Background worker that consumes the "ai_parse_tasks" queue, calls Gemini to
turn a DRAFT task's raw text/audio into structured fields, and advances it
to PENDING_MERCHANT_CONFIRMATION. Notifies the merchant via WhatsApp with a
summary to confirm.

Run standalone:
    python -m app.workers.ai_parse_worker
"""
import logging
import signal
import sys
import uuid

from app.db.session import SessionLocal
from app.models.task import Task
from app.services import ai_service, whatsapp_client
from app.services.queue import dequeue_blocking, promote_due_retries, retry_or_dead_letter
from app.services.storage_service import download_bytes
from app.services.task_service import apply_ai_extraction
from app.services.notification_service import notify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

AI_PARSE_QUEUE = "ai_parse_tasks"
_shutdown = False


def _handle_shutdown(signum, frame):
    global _shutdown
    _shutdown = True


def process_ai_parse_task(payload: dict) -> None:
    task_id = uuid.UUID(payload["task_id"])
    db = SessionLocal()
    try:
        task: Task | None = db.get(Task, task_id)
        if task is None:
            logger.warning("AI parse job for missing task %s", task_id)
            return

        try:
            if task.source_audio_key:
                audio_bytes = download_bytes(task.source_audio_key)
                extraction, raw = ai_service.extract_task_from_audio(audio_bytes)
            else:
                extraction, raw = ai_service.extract_task_from_text(task.requirements or "")
        except ai_service.AIParsingError:
            logger.exception("AI parsing failed for task %s", task_id)
            notify(
                db,
                user_id=_merchant_user_id(db, task),
                task_id=task.id,
                channel="WHATSAPP",
                event_type="AI_PARSE_FAILED",
                body="We couldn't understand your task request. Please try describing it again in a bit more detail.",
            )
            db.commit()
            return

        apply_ai_extraction(db, task, extraction, raw)
        db.commit()
        logger.info("Task %s parsed and moved to PENDING_MERCHANT_CONFIRMATION", task.id)

        location = task.farm_location or {}
        location_text = location.get("address") or location.get("label") or location.get("state") or "Not specified"
        agriculture = task.agricultural_details or {}
        structured_bits = [
            f"Crop: {agriculture['crop_type']}" if agriculture.get("crop_type") else None,
            f"Livestock: {agriculture['livestock_type']}" if agriculture.get("livestock_type") else None,
            f"Quantity: {agriculture['quantity']} {agriculture.get('quantity_unit', '')}" if agriculture.get("quantity") else None,
            f"Workers: {agriculture['worker_count']}" if agriculture.get("worker_count") else None,
        ]
        structured_text = ", ".join(item for item in structured_bits if item) or "No additional structured details"
        logistics_text = f"\nLogistics reference: {task.logistics_handoff_reference}" if task.logistics_handoff_reference else ""
        summary = (
            f"Here's what we understood:\n\n"
            f"*{task.title}*\n"
            f"Category: {task.category}\n"
            f"Service: {task.service_category.value if task.service_category else 'General task'}\n"
            f"Location: {location_text}\n"
            f"Agricultural details: {structured_text}{logistics_text}\n"
            f"Details: {task.requirements}\n"
            f"Suggested pay: {task.suggested_payout} {extraction.currency}\n\n"
            f"Reply CONFIRM to publish this task, or CANCEL to discard it."
        )
        notify(
            db,
            user_id=_merchant_user_id(db, task),
            task_id=task.id,
            channel="WHATSAPP",
            event_type="TASK_PENDING_CONFIRMATION",
            body=summary,
        )
        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Failed processing AI parse job for task %s", task_id)
        raise
    finally:
        db.close()


def _merchant_user_id(db, task: Task) -> uuid.UUID:
    from app.models.user import Merchant

    merchant = db.get(Merchant, task.merchant_id)
    return merchant.user_id


def run() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    logger.info("AI parse worker started, listening on queue '%s'", AI_PARSE_QUEUE)
    while not _shutdown:
        promote_due_retries(AI_PARSE_QUEUE)
        job = dequeue_blocking(AI_PARSE_QUEUE, timeout=5)
        if job is None:
            continue
        if job.get("job_type") == "ai_parse_task":
            try:
                process_ai_parse_task(job["payload"])
            except Exception as exc:
                retry_or_dead_letter(AI_PARSE_QUEUE, job, exc)
        else:
            logger.warning("Unknown job type on %s queue: %s", AI_PARSE_QUEUE, job.get("job_type"))


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
