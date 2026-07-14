import json
import time
import uuid
from typing import Any

import redis

from app.core.config import settings

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def enqueue(queue_name: str, job_type: str, payload: dict[str, Any], *, max_attempts: int | None = None) -> str:
    """
    Push a job onto a Redis list queue. Jobs are plain JSON:
    {"job_id": ..., "job_type": ..., "payload": {...}}
    """
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "job_type": job_type,
        "payload": payload,
        "attempt": 0,
        "max_attempts": max_attempts or settings.job_max_attempts,
        "enqueued_at": int(time.time()),
    }
    get_redis().rpush(queue_name, json.dumps(job))
    return job_id


def dequeue_blocking(queue_name: str, timeout: int = 5) -> dict[str, Any] | None:
    """
    Blocking pop with a timeout (seconds). Returns None on timeout so the
    worker loop can check for shutdown signals periodically.
    """
    result = get_redis().blpop([queue_name], timeout=timeout)
    if result is None:
        return None
    _, raw = result
    return json.loads(raw)


def retry_or_dead_letter(queue_name: str, job: dict[str, Any], error: Exception | str) -> bool:
    """Schedule exponential retry, retaining exhausted work in a dead-letter list."""
    client = get_redis()
    job["attempt"] = int(job.get("attempt", 0)) + 1
    job["last_error"] = str(error)
    job["failed_at"] = int(time.time())
    if job["attempt"] >= int(job.get("max_attempts", settings.job_max_attempts)):
        client.rpush(f"{queue_name}:dead", json.dumps(job))
        return False
    delay = settings.job_retry_base_seconds * (2 ** (job["attempt"] - 1))
    client.zadd(f"{queue_name}:delayed", {json.dumps(job): time.time() + delay})
    return True


def promote_due_retries(queue_name: str, limit: int = 100) -> int:
    client = get_redis()
    delayed = f"{queue_name}:delayed"
    due = client.zrangebyscore(delayed, 0, time.time(), start=0, num=limit)
    if not due:
        return 0
    pipe = client.pipeline()
    for raw in due:
        pipe.zrem(delayed, raw)
        pipe.rpush(queue_name, raw)
    pipe.execute()
    return len(due)
