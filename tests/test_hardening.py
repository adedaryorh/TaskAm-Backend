import hashlib
import hmac
import json

from app.models.base import TaskStatus, TASK_STATE_TRANSITIONS
from app.services import opay_service, paystack_service, queue


def test_unfunded_claim_can_return_to_marketplace():
    assert TaskStatus.PUBLISHED in TASK_STATE_TRANSITIONS[TaskStatus.CLAIMED]


def test_terminal_tasks_stay_terminal():
    assert TASK_STATE_TRANSITIONS[TaskStatus.COMPLETED] == set()
    assert TASK_STATE_TRANSITIONS[TaskStatus.CANCELLED] == set()


def test_paystack_signature(monkeypatch):
    monkeypatch.setattr(paystack_service.settings, "paystack_secret_key", "secret")
    body = b'{"event":"charge.success"}'
    signature = hmac.new(b"secret", body, hashlib.sha512).hexdigest()
    assert paystack_service.verify_webhook_signature(body, signature)
    assert not paystack_service.verify_webhook_signature(body, "bad")


def test_opay_signature(monkeypatch):
    monkeypatch.setattr(opay_service.settings, "opay_webhook_secret", "secret")
    body = b'{"status":"SUCCESS"}'
    signature = hmac.new(b"secret", body, hashlib.sha512).hexdigest()
    assert opay_service.verify_webhook_signature(body, signature)


def test_exhausted_job_goes_to_dead_letter(monkeypatch):
    import fakeredis
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(queue, "get_redis", lambda: client)
    job = {"job_id": "1", "job_type": "x", "payload": {}, "attempt": 0, "max_attempts": 1}
    assert queue.retry_or_dead_letter("jobs", job, "boom") is False
    assert json.loads(client.lpop("jobs:dead"))["last_error"] == "boom"
