"""
Background worker that consumes the "whatsapp_messages" Redis queue and
turns each inbound message into a DRAFT Task.

Run standalone:
    python -m app.workers.whatsapp_worker

For text messages: creates a DRAFT task with the raw text as `requirements`
and enqueues an "ai_parse_task" job for Phase 5 to pick up.

For voice notes: downloads the audio from WhatsApp, uploads it to object
storage, creates a DRAFT task referencing the storage key, and enqueues the
same "ai_parse_task" job (Phase 5's Gemini integration will transcribe/parse
directly from the stored audio).
"""
import logging
import signal
import sys

from app.db.session import SessionLocal
from app.models.base import TaskStatus
from app.models.task import Task
from app.services import whatsapp_client
from app.services.queue import dequeue_blocking, enqueue, promote_due_retries, retry_or_dead_letter
from app.services.storage_service import upload_bytes
from app.services.merchant_service import get_or_create_merchant_by_whatsapp_id
from app.services.task_service import create_draft_task_from_whatsapp, confirm_task, cancel_task

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

WHATSAPP_QUEUE = "whatsapp_messages"
AI_PARSE_QUEUE = "ai_parse_tasks"

_shutdown = False


def _handle_shutdown(signum, frame):
    global _shutdown
    logger.info("Shutdown signal received, finishing current job then exiting...")
    _shutdown = True


def process_whatsapp_message(payload: dict) -> None:
    message_id = payload["message_id"]
    from_wa_id = payload["from_wa_id"]
    message_type = payload["message_type"]
    text_body = payload.get("text_body")
    media_id = payload.get("media_id")

    db = SessionLocal()
    try:
        merchant = get_or_create_merchant_by_whatsapp_id(db, from_wa_id)

        keyword = (text_body or "").strip().upper()
        if keyword in ("CONFIRM", "CANCEL"):
            pending_task = (
                db.query(Task)
                .filter(Task.merchant_id == merchant.id, Task.status == TaskStatus.PENDING_MERCHANT_CONFIRMATION)
                .order_by(Task.created_at.desc())
                .first()
            )
            if pending_task is None:
                _safe_send(from_wa_id, "You don't have a task waiting for confirmation right now.")
                return

            if keyword == "CONFIRM":
                confirm_task(db, pending_task, actor_user_id=None)
                db.commit()
                _safe_send(from_wa_id, f'Published! Students can now claim "{pending_task.title}".')
            else:
                cancel_task(db, pending_task, actor_user_id=None)
                db.commit()
                _safe_send(from_wa_id, "Task cancelled.")
            return

        source_audio_key = None
        requirements = text_body

        if message_type in ("audio", "voice") and media_id:
            try:
                media_url = whatsapp_client.get_media_url(media_id)
                audio_bytes = whatsapp_client.download_media(media_url)
                source_audio_key = f"whatsapp-voice-notes/{message_id}.ogg"
                upload_bytes(source_audio_key, audio_bytes, content_type="audio/ogg")
            except Exception:
                logger.exception("Failed to fetch/store voice note for message %s", message_id)

        task = create_draft_task_from_whatsapp(
            db,
            merchant_id=merchant.id,
            source_whatsapp_message_id=message_id,
            requirements=requirements,
            source_audio_key=source_audio_key,
        )
        db.commit()
        logger.info("Created DRAFT task %s from WhatsApp message %s", task.id, message_id)

        # Hand off to Phase 5's AI parsing worker.
        enqueue(AI_PARSE_QUEUE, job_type="ai_parse_task", payload={"task_id": str(task.id)})

        try:
            whatsapp_client.send_text_message(
                from_wa_id,
                "Got it! We're processing your task and will send you a summary to confirm shortly.",
            )
        except Exception:
            # Don't fail the job over a notification send failure — the task
            # is already durably created. Common in dev when WhatsApp
            # credentials aren't configured yet.
            logger.warning("Could not send WhatsApp acknowledgement for %s (credentials likely unset)", message_id)

    except Exception:
        db.rollback()
        logger.exception("Failed to process WhatsApp message %s", message_id)
        raise
    finally:
        db.close()


def _safe_send(to_wa_id: str, body: str) -> None:
    try:
        whatsapp_client.send_text_message(to_wa_id, body)
    except Exception:
        logger.warning("Could not send WhatsApp message to %s (credentials likely unset)", to_wa_id)


def run() -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    logger.info("WhatsApp worker started, listening on queue '%s'", WHATSAPP_QUEUE)
    while not _shutdown:
        promote_due_retries(WHATSAPP_QUEUE)
        job = dequeue_blocking(WHATSAPP_QUEUE, timeout=5)
        if job is None:
            continue
        if job.get("job_type") == "process_whatsapp_message":
            try:
                process_whatsapp_message(job["payload"])
            except Exception as exc:
                retry_or_dead_letter(WHATSAPP_QUEUE, job, exc)
        else:
            logger.warning("Unknown job type on %s queue: %s", WHATSAPP_QUEUE, job.get("job_type"))


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
