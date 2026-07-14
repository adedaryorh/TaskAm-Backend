import json

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.service_auth import platform_service_headers
from app.models.base import ServiceCategory
from app.models.task import Task
from app.models.user import User
from app.schemas.logistics import (
    LogisticsBookingRequestWire, LogisticsCoordinate, LogisticsQuoteRequest,
    LogisticsShipment, LogisticsTimeWindow,
)
from app.services.integration_service import enqueue_farmsense_status

QUOTE_PATH = "/internal/v1/agricultural/quotes"
BOOKING_PATH = "/internal/v1/agricultural/bookings"

LOGISTICS_STATUS_MAP = {
    "pending": "requested", "awaiting_payment": "quoted", "paid": "confirmed",
    "dispatching": "booked", "assigned": "provider_assigned", "picked_up": "picked_up",
    "in_transit": "in_transit", "delivered": "delivered", "cancelled": "cancelled", "failed": "failed",
}


def _post(path: str, payload: dict) -> dict:
    if not settings.logistics_service_url or not settings.logistics_service_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Logistics service is not configured")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    headers = platform_service_headers(
        settings.taskam_service_identity, settings.logistics_service_secret, "POST", path, body
    )
    idempotency_key = payload.pop("idempotency_key", "")
    if not idempotency_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key is required")
    headers["Idempotency-Key"] = idempotency_key
    try:
        response = httpx.post(
            settings.logistics_service_url.rstrip("/") + path,
            content=body, headers=headers, timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Logistics request failed") from exc


def _quote_payload(db: Session, task: Task, idempotency_key: str) -> LogisticsQuoteRequest:
    if task.service_category != ServiceCategory.TRANSPORT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request is not a transport service")
    requester = db.get(User, task.requester_user_id)
    details = (task.agricultural_details or {}).get("transport") or {}
    pickup, dropoff = details.get("pickup") or {}, details.get("dropoff") or {}
    required = (
        requester and requester.platform_user_id and task.marketplace_request_id,
        pickup.get("latitude") is not None and pickup.get("longitude") is not None,
        dropoff.get("latitude") is not None and dropoff.get("longitude") is not None,
        details.get("pickup_window_start") and details.get("pickup_window_end"),
        details.get("delivery_window_start") and details.get("delivery_window_end"),
    )
    if not all(required):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Transport request lacks Logistics coordinates or time windows")
    return LogisticsQuoteRequest(
        platform_user_id=requester.platform_user_id,
        farmsense_request_id=task.farmsense_request_id,
        marketplace_request_id=task.marketplace_request_id,
        idempotency_key=idempotency_key,
        pickup=LogisticsCoordinate(lat=pickup["latitude"], lng=pickup["longitude"], address=pickup.get("address")),
        dropoff=LogisticsCoordinate(lat=dropoff["latitude"], lng=dropoff["longitude"], address=dropoff.get("address")),
        shipment=LogisticsShipment(
            produce_type=details.get("commodity") or (task.agricultural_details or {}).get("crop_type") or "agricultural produce",
            quantity=details.get("load_quantity") or (task.agricultural_details or {}).get("quantity"),
            quantity_unit=details.get("load_unit") or (task.agricultural_details or {}).get("quantity_unit") or "unit",
            weight_kg=details.get("weight_kg"), packaging=details.get("packaging", "bag"),
            requires_refrigeration=details.get("requires_refrigeration", False),
            cold_chain_min_c=details.get("cold_chain_min_c"), cold_chain_max_c=details.get("cold_chain_max_c"),
            pickup_window=LogisticsTimeWindow(start_at=details["pickup_window_start"], end_at=details["pickup_window_end"]),
            delivery_window=LogisticsTimeWindow(start_at=details["delivery_window_start"], end_at=details["delivery_window_end"]),
            handling_notes=details.get("handling_notes"), loading_notes=details.get("loading_notes"),
        ),
    )


def request_quotes(db: Session, task: Task, idempotency_key: str) -> list[dict]:
    wire = _quote_payload(db, task, idempotency_key)
    envelope = _post(QUOTE_PATH, wire.model_dump(mode="json", exclude_none=True))
    quote = (envelope.get("data") or {}).get("quote") if envelope.get("success") else None
    if not isinstance(quote, dict) or not quote.get("id"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Logistics returned an invalid quote")
    task.logistics_quotes = [quote]
    db.commit()
    return task.logistics_quotes


def book_quote(db: Session, task: Task, quote_id: str, idempotency_key: str) -> dict:
    if not any(quote.get("id") == quote_id for quote in (task.logistics_quotes or [])):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quote does not belong to this request")
    wire = LogisticsBookingRequestWire(quote_id=quote_id, idempotency_key=idempotency_key)
    envelope = _post(BOOKING_PATH, wire.model_dump(mode="json"))
    booking = (envelope.get("data") or {}).get("booking") if envelope.get("success") else None
    if not isinstance(booking, dict) or not booking.get("id") or booking.get("status") not in LOGISTICS_STATUS_MAP:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Logistics returned an invalid booking")
    normalized_status = LOGISTICS_STATUS_MAP[booking["status"]]
    task.logistics_delivery_id = booking["id"]
    task.selected_logistics_quote_id = quote_id
    enqueue_farmsense_status(
        db, task, "logistics.booking.created",
        normalized_status_override=normalized_status,
        extra_data={"logistics_status": normalized_status, "internal_status": booking["status"]},
    )
    db.commit()
    return {
        "platform_user_id": booking.get("platform_user_id"),
        "farmsense_request_id": booking.get("farmsense_request_id"),
        "marketplace_request_id": booking.get("marketplace_request_id"),
        "logistics_delivery_id": booking["id"],
        "status": normalized_status,
    }
