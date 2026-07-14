from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


@dataclass
class InboundMessage:
    message_id: str
    from_wa_id: str
    timestamp: str
    message_type: str  # "text" | "audio" | "image" | "document" | ...
    text_body: str | None = None
    media_id: str | None = None


def verify_webhook_challenge(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    """
    Meta's webhook handshake: GET request with hub.mode=subscribe,
    hub.verify_token, hub.challenge. Return the challenge string to confirm
    the endpoint, or None if verification fails.
    """
    if mode == "subscribe" and token == settings.whatsapp_verify_token and challenge is not None:
        return challenge
    return None


def parse_webhook_payload(payload: dict[str, Any]) -> list[InboundMessage]:
    """
    Normalizes a WhatsApp Cloud API webhook payload into a flat list of
    InboundMessage. Payload shape:
    entry[].changes[].value.messages[] (+ contacts[] for the sender profile)
    """
    messages: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                msg_type = msg.get("type")
                text_body = None
                media_id = None
                if msg_type == "text":
                    text_body = msg.get("text", {}).get("body")
                elif msg_type in ("audio", "voice"):
                    media_id = msg.get("audio", {}).get("id")
                elif msg_type == "image":
                    media_id = msg.get("image", {}).get("id")
                elif msg_type == "document":
                    media_id = msg.get("document", {}).get("id")

                messages.append(
                    InboundMessage(
                        message_id=msg.get("id"),
                        from_wa_id=msg.get("from"),
                        timestamp=msg.get("timestamp"),
                        message_type=msg_type,
                        text_body=text_body,
                        media_id=media_id,
                    )
                )
    return messages


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.whatsapp_access_token}"}


def get_media_url(media_id: str) -> str:
    resp = httpx.get(f"{settings.whatsapp_api_base}/{media_id}", headers=_auth_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()["url"]


def download_media(media_url: str) -> bytes:
    resp = httpx.get(media_url, headers=_auth_headers(), timeout=30)
    resp.raise_for_status()
    return resp.content


def send_text_message(to_wa_id: str, body: str) -> None:
    url = f"{settings.whatsapp_api_base}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": body},
    }
    resp = httpx.post(url, headers=_auth_headers(), json=payload, timeout=15)
    resp.raise_for_status()
