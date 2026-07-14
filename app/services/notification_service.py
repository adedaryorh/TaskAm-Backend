import logging
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User
from app.services import whatsapp_client
from app.core.config import settings

logger = logging.getLogger(__name__)


def notify(
    db: Session,
    user_id: uuid.UUID,
    channel: str,  # "WHATSAPP" | "EMAIL"
    event_type: str,
    body: str,
    task_id: uuid.UUID | None = None,
) -> Notification:
    """
    Writes a Notification row (added to session, not committed — caller
    commits) and attempts immediate dispatch. Dispatch failures never raise:
    the row's `sent`/`error` fields record what happened so a retry worker
    could pick it up later without losing the record of what was owed.
    """
    notification = Notification(
        user_id=user_id,
        task_id=task_id,
        channel=channel,
        event_type=event_type,
        body=body,
    )
    db.add(notification)
    db.flush()

    dispatch_notification(db, notification)
    return notification


def dispatch_notification(db: Session, notification: Notification) -> Notification:
    """Attempt one delivery. Failed rows remain eligible for the retry worker."""
    notification.attempts += 1
    notification.error = None
    try:
        user = db.get(User, notification.user_id)
        if user is None:
            raise ValueError(f"No user {notification.user_id} to notify")
        if notification.channel == "WHATSAPP":
            # WhatsApp ID is the merchant's phone number without '+'; users
            # created via WhatsApp store it on Merchant.whatsapp_id, but for
            # simplicity we derive it from the phone number here too.
            wa_id = user.phone_number.lstrip("+")
            whatsapp_client.send_text_message(wa_id, notification.body)
            notification.sent = True
        elif notification.channel == "EMAIL":
            if not user.email:
                raise ValueError("User has no email address")
            _send_email(user.email, notification.event_type, notification.body)
            notification.sent = True
        else:
            raise ValueError(f"Unknown channel: {notification.channel}")
    except Exception as e:
        logger.warning("Notification dispatch failed (event=%s, user=%s): %s", notification.event_type, notification.user_id, e)
        notification.error = str(e)
        delay = min(3600, 2 ** min(notification.attempts, 10) * 5)
        notification.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    else:
        notification.sent_at = datetime.now(timezone.utc)
        notification.next_attempt_at = None
    return notification


def _send_email(to_email: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise RuntimeError("SMTP is not configured")
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = subject.replace("_", " ").title()
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
