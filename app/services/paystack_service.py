"""
Paystack integration: initialize a checkout transaction for a funded task,
and verify inbound webhook signatures.

NOTE ON API SHAPE: this sandbox has no network access to api.paystack.co, so
the request/response shapes below have NOT been exercised against a live
call — verify against https://paystack.com/docs/api/transaction/ before
relying on this in production. The parts most worth double-checking:
  - POST /transaction/initialize request/response fields (reference,
    authorization_url are Paystack's documented field names as of last
    check)
  - the webhook signature scheme: Paystack signs the raw request body with
    HMAC-SHA512 using your secret key and sends it in the
    `x-paystack-signature` header (documented behavior) — this IS
    implemented exactly as documented, just not tested against a live
    webhook delivery.
Everything else (idempotent webhook handling, raw payload storage, state
transition on success) follows the same pattern as opay_service.py and IS
exercised by the test suite with a fake signature.
"""
import hashlib
import hmac
import logging
import uuid

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class PaystackError(Exception):
    pass


def initialize_transaction(reference: str, amount_naira: float, email: str, currency: str = "NGN") -> dict:
    """
    Creates a Paystack transaction and returns {"reference": ..., "checkout_url": ...}.
    Amount is sent in kobo (smallest currency unit) per Paystack convention.
    `email` is required by Paystack's API even for a marketplace escrow
    payment with no real "customer" concept — use the merchant's contact
    email, or a placeholder like f"{whatsapp_id}@taskam.placeholder" if none
    is on file.
    """
    amount_kobo = int(round(amount_naira * 100))
    payload = {
        "reference": reference,
        "amount": amount_kobo,
        "currency": currency,
        "email": email,
    }
    headers = {
        "Authorization": f"Bearer {settings.paystack_secret_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            f"{settings.paystack_base_url}/transaction/initialize",
            json=payload,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as e:
        raise PaystackError(f"Failed to initialize Paystack transaction: {e}") from e

    result = data.get("data", {})
    return {
        "reference": result.get("reference") or reference,
        "checkout_url": result.get("authorization_url"),
    }


def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    # Fail closed: with no secret configured, an attacker could otherwise
    # "verify" by signing with the empty key.
    if not settings.paystack_secret_key or not signature_header:
        return False
    computed = hmac.new(settings.paystack_secret_key.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature_header)


def new_payment_reference(task_id: uuid.UUID) -> str:
    return f"taskam-{task_id}"


def _post(path: str, payload: dict) -> dict:
    try:
        response = httpx.post(
            f"{settings.paystack_base_url}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {settings.paystack_secret_key}"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("status"):
            raise PaystackError(data.get("message", "Paystack operation failed"))
        return data.get("data", {})
    except httpx.HTTPError as exc:
        raise PaystackError(f"Paystack operation failed: {exc}") from exc


def create_transfer_recipient(name: str, account_number: str, bank_code: str) -> str:
    data = _post("/transferrecipient", {
        "type": "nuban", "name": name, "account_number": account_number,
        "bank_code": bank_code, "currency": "NGN",
    })
    return data["recipient_code"]


def initiate_transfer(reference: str, amount_naira: float, recipient_code: str, reason: str) -> str:
    data = _post("/transfer", {
        "source": "balance", "amount": int(round(amount_naira * 100)),
        "recipient": recipient_code, "reference": reference, "reason": reason,
    })
    return data.get("transfer_code") or data.get("reference") or reference


def initiate_refund(transaction_reference: str, amount_naira: float) -> str:
    data = _post("/refund", {"transaction": transaction_reference, "amount": int(round(amount_naira * 100))})
    return str(data.get("id") or data.get("transaction", {}).get("reference") or transaction_reference)
