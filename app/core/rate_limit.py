import time

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.services.queue import get_redis


def client_ip(request: Request) -> str:
    """Resolve the real client IP. Behind Caddy every connection comes from the
    proxy container, so trust X-Forwarded-For only when explicitly enabled."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # Client IP is the first entry; later hops are proxies.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(bucket: str, key_part: str, limit: int, window_seconds: int) -> None:
    """Redis-backed fixed-window limiter shared by all API instances."""
    window = int(time.time()) // window_seconds
    key = f"rate:{bucket}:{key_part}:{window}"
    client = get_redis()
    count = client.incr(key)
    if count == 1:
        client.expire(key, window_seconds + 1)
    if count > limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")


def enforce_webhook_rate_limit(request: Request) -> None:
    _enforce_rate_limit(
        "webhook", client_ip(request), settings.webhook_rate_limit, settings.webhook_rate_window_seconds
    )


def enforce_auth_rate_limit(request: Request) -> None:
    """Stricter limiter for credential endpoints (login, signup, claim codes)."""
    _enforce_rate_limit(
        "auth", client_ip(request), settings.auth_rate_limit, settings.auth_rate_window_seconds
    )
