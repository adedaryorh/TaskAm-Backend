"""Regression tests for the security-hardening fixes."""
import hashlib
import hmac
from decimal import Decimal

import pytest

from app.routers import webhooks
from app.services import opay_service, paystack_service, payment_service


# --- WhatsApp inbound signature (X-Hub-Signature-256) ---

def _meta_sig(secret: bytes, body: bytes) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_whatsapp_signature_valid(monkeypatch):
    monkeypatch.setattr(webhooks.settings, "whatsapp_app_secret", "app-secret")
    body = b'{"entry":[]}'
    assert webhooks._verify_meta_signature(body, _meta_sig(b"app-secret", body))


def test_whatsapp_signature_rejects_bad_or_missing(monkeypatch):
    monkeypatch.setattr(webhooks.settings, "whatsapp_app_secret", "app-secret")
    body = b'{"entry":[]}'
    assert not webhooks._verify_meta_signature(body, None)
    assert not webhooks._verify_meta_signature(body, "sha256=deadbeef")
    assert not webhooks._verify_meta_signature(body, _meta_sig(b"wrong", body))


def test_whatsapp_signature_fails_closed_without_secret(monkeypatch):
    monkeypatch.setattr(webhooks.settings, "whatsapp_app_secret", "")
    body = b'{"entry":[]}'
    # Empty secret must reject even a signature HMAC'd with the empty key.
    assert not webhooks._verify_meta_signature(body, _meta_sig(b"", body))


# --- Gateway verifiers fail closed on empty secret ---

def test_paystack_verifier_fails_closed_without_secret(monkeypatch):
    monkeypatch.setattr(paystack_service.settings, "paystack_secret_key", "")
    body = b'{"event":"charge.success"}'
    empty_key_sig = hmac.new(b"", body, hashlib.sha512).hexdigest()
    assert not paystack_service.verify_webhook_signature(body, empty_key_sig)


def test_opay_verifier_fails_closed_without_secret(monkeypatch):
    monkeypatch.setattr(opay_service.settings, "opay_webhook_secret", "")
    body = b'{"status":"SUCCESS"}'
    empty_key_sig = hmac.new(b"", body, hashlib.sha512).hexdigest()
    assert not opay_service.verify_webhook_signature(body, empty_key_sig)


# --- Payment webhook amount verification ---

class _FakePayment:
    def __init__(self, amount, currency="NGN"):
        self.amount = amount
        self.currency = currency


def test_amount_match_requires_full_escrow_amount():
    payment = _FakePayment(Decimal("5000.00"))
    assert payment_service._amount_matches(payment, 500_000, "NGN")       # exact
    assert payment_service._amount_matches(payment, 500_100, "NGN")       # overpay ok
    assert not payment_service._amount_matches(payment, 100, "NGN")       # ₦1 partial
    assert not payment_service._amount_matches(payment, 499_999, "NGN")


def test_amount_match_rejects_missing_amount_or_wrong_currency():
    payment = _FakePayment(Decimal("5000.00"))
    assert not payment_service._amount_matches(payment, None, "NGN")
    assert not payment_service._amount_matches(payment, 500_000, "USD")
    # Missing currency in the event falls back to trusting the amount only.
    assert payment_service._amount_matches(payment, 500_000, None)


def test_paystack_event_parser_extracts_amount():
    payload = {
        "event": "charge.success",
        "data": {"reference": "taskam-x", "status": "success", "amount": 500000, "currency": "NGN"},
    }
    reference, is_success, is_failure, amount_kobo, currency = payment_service._parse_paystack_event(payload)
    assert (reference, is_success, is_failure) == ("taskam-x", True, False)
    assert amount_kobo == 500000
    assert currency == "NGN"


def test_opay_event_parser_extracts_nested_amount():
    payload = {"orderNo": "taskam-y", "status": "SUCCESS", "amount": {"total": 250000, "currency": "NGN"}}
    reference, is_success, is_failure, amount_kobo, currency = payment_service._parse_opay_event(payload)
    assert (reference, is_success, is_failure) == ("taskam-y", True, False)
    assert amount_kobo == 250000
    assert currency == "NGN"


# --- Claim-code brute-force cap ---

def test_claim_code_attempt_cap(monkeypatch):
    import fakeredis
    from fastapi import HTTPException
    from app.services import auth_service

    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(auth_service, "get_redis", lambda: client)
    client.setex("merchant-claim:+2348000000000", 600, "123456")

    class _Payload:
        phone_number = "+2348000000000"
        code = "000000"
        password = "irrelevant-password"
        full_name = "X"
        business_name = "Y"

    for _ in range(auth_service._CLAIM_CODE_MAX_ATTEMPTS):
        with pytest.raises(HTTPException) as exc:
            auth_service.complete_merchant_claim(None, _Payload())
        assert exc.value.status_code == 400

    # Next attempt hits the cap and burns the stored code.
    with pytest.raises(HTTPException) as exc:
        auth_service.complete_merchant_claim(None, _Payload())
    assert exc.value.status_code == 429
    assert client.get("merchant-claim:+2348000000000") is None
