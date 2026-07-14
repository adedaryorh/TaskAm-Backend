"""
OPay integration: create a checkout order for a funded task, and verify
inbound webhook signatures.

NOTE ON API SHAPE: this sandbox has no network access to opaycheckout.com,
so the request/response shapes below have NOT been verified against a live
call — verify against OPay's current merchant API docs
(https://documentation.opaycheckout.com) before relying on this in
production, in particular:
  - the exact create-order endpoint path and required fields
  - the exact webhook signature header name and hashing scheme (this
    assumes HMAC-SHA512 of the raw request body, hex-encoded, which is
    OPay's documented approach for their Cashier API as of last check, but
    reconfirm)
Everything else here (idempotent webhook handling, raw payload storage,
state transition on success) follows the codebase's general patterns and IS
exercised by the test suite with a fake signature.
"""
import hashlib
import hmac
import logging
import uuid

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class OPayError(Exception):
    pass


def create_checkout_order(reference: str, amount_naira: float, currency: str = "NGN") -> dict:
    """
    Creates a checkout order with OPay and returns {"order_id": ..., "checkout_url": ...}.
    Amount is sent in kobo (smallest currency unit) per OPay convention.
    """
    amount_kobo = int(round(amount_naira * 100))
    payload = {
        "reference": reference,
        "amount": {"total": amount_kobo, "currency": currency},
        "merchantId": settings.opay_merchant_id,
        "callbackUrl": None,  # set to your public webhook URL in production
    }
    headers = {
        "Authorization": f"Bearer {settings.opay_public_key}",
        "MerchantId": settings.opay_merchant_id,
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            f"{settings.opay_base_url}/api/v1/international/cashier/create",
            json=payload,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise OPayError(f"Failed to create OPay order: {e}") from e

    result = data.get("data", {})
    return {
        "order_id": result.get("orderNo") or reference,
        "checkout_url": result.get("cashierUrl"),
    }


def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header:
        return False
    computed = hmac.new(settings.opay_webhook_secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature_header)


def new_payment_reference(task_id: uuid.UUID) -> str:
    return f"taskam-{task_id}"


def _post(path: str, payload: dict) -> dict:
    headers = {"Authorization": f"Bearer {settings.opay_secret_key}", "MerchantId": settings.opay_merchant_id}
    try:
        response = httpx.post(f"{settings.opay_base_url}{path}", json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        if str(data.get("code", "00000")) not in {"00000", "SUCCESS"}:
            raise OPayError(data.get("message", "OPay operation failed"))
        return data.get("data", {})
    except httpx.HTTPError as exc:
        raise OPayError(f"OPay operation failed: {exc}") from exc


def initiate_transfer(reference: str, amount_naira: float, account_number: str, bank_code: str, account_name: str) -> str:
    data = _post("/api/v1/international/transfer/create", {
        "reference": reference, "amount": int(round(amount_naira * 100)), "currency": "NGN",
        "receiver": {"accountNumber": account_number, "bankCode": bank_code, "name": account_name},
    })
    return data.get("orderNo") or data.get("reference") or reference


def initiate_refund(transaction_reference: str, amount_naira: float, refund_reference: str) -> str:
    data = _post("/api/v1/international/cashier/refund", {
        "orderNo": transaction_reference, "reference": refund_reference,
        "amount": {"total": int(round(amount_naira * 100)), "currency": "NGN"},
    })
    return data.get("orderNo") or data.get("reference") or refund_reference
