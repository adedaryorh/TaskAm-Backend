import time

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.services.queue import get_redis


def enforce_webhook_rate_limit(request: Request) -> None:
    """Redis-backed fixed-window limiter shared by all API instances."""
    client_ip = request.client.host if request.client else "unknown"
    window = int(time.time()) // settings.webhook_rate_window_seconds
    key = f"rate:webhook:{client_ip}:{window}"
    client = get_redis()
    count = client.incr(key)
    if count == 1:
        client.expire(key, settings.webhook_rate_window_seconds + 1)
    if count > settings.webhook_rate_limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Webhook rate limit exceeded")
