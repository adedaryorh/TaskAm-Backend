import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.services.queue import get_redis


def webhook_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Canonical webhook signature: HMAC-SHA256(timestamp + '.' + raw body)."""
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


# Backward-compatible name used by older callers for webhook signing only.
signature_for = webhook_signature


def request_signature(secret: str, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((method.upper(), path, timestamp, nonce, digest)).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def platform_service_headers(
    service: str, secret: str, method: str, path: str, body: bytes,
    timestamp: int | None = None, nonce: str | None = None,
) -> dict[str, str]:
    timestamp_text = str(timestamp if timestamp is not None else int(time.time()))
    nonce_text = nonce or secrets.token_urlsafe(24)
    signature = request_signature(secret, method, path, timestamp_text, nonce_text, body)
    return {
        "content-type": "application/json",
        "x-platform-service": service,
        "x-platform-timestamp": timestamp_text,
        "x-platform-nonce": nonce_text,
        "x-platform-signature": f"sha256={signature}",
    }


def _service_secret(service: str) -> str:
    return {
        "farmsense": settings.farmsense_inbound_secret,
        "logistics": settings.logistics_service_secret,
    }.get(service, "")


async def require_platform_service(request: Request) -> str:
    service = request.headers.get("x-platform-service", "").strip().lower()
    timestamp = request.headers.get("x-platform-timestamp", "")
    nonce = request.headers.get("x-platform-nonce", "").strip()
    supplied = request.headers.get("x-platform-signature", "").removeprefix("sha256=")
    secret = _service_secret(service)
    try:
        timestamp_value = int(timestamp)
    except ValueError:
        timestamp_value = 0
    if (
        not service or not secret or not nonce or
        abs(int(time.time()) - timestamp_value) > settings.service_auth_max_skew_seconds
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service authentication")
    body = await request.body()
    expected = request_signature(secret, request.method, request.url.path, timestamp, nonce, body)
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service authentication")
    replay_key = f"service-auth-nonce:{service}:{nonce}"
    accepted = get_redis().set(replay_key, "1", nx=True, ex=settings.service_auth_max_skew_seconds)
    if not accepted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Replayed service request")
    request.state.platform_service = service
    return service


async def require_farmsense_service(request: Request) -> None:
    try:
        service = await require_platform_service(request)
    except HTTPException:
        if not settings.allow_legacy_farmsense_auth:
            raise
        timestamp = request.headers.get("x-farmsense-timestamp", "")
        supplied = request.headers.get("x-farmsense-signature", "").removeprefix("sha256=")
        try:
            fresh = abs(int(time.time()) - int(timestamp)) <= settings.service_auth_max_skew_seconds
        except ValueError:
            fresh = False
        expected = webhook_signature(settings.farmsense_inbound_secret, timestamp, await request.body())
        if not fresh or not hmac.compare_digest(expected, supplied):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service authentication")
        service = "farmsense"
    if service != "farmsense":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="FarmSense service identity required")


def signed_headers(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    timestamp_text = str(timestamp if timestamp is not None else int(time.time()))
    return {
        "content-type": "application/json",
        "x-taskam-timestamp": timestamp_text,
        "x-taskam-signature": f"sha256={webhook_signature(secret, timestamp_text, body)}",
        "x-taskam-event-version": "1",
    }
