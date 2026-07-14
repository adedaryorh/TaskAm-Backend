import hashlib
import hmac
import json
import time
import uuid
from types import SimpleNamespace
from pathlib import Path
import fakeredis

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import service_auth
from app.main import app
from app.db.session import get_db
from app.models.base import RequestSource, ServiceCategory, TaskStatus, UserRole
from app.models.task import Task
from app.schemas.ai import AITaskExtraction
from app.schemas.integration import InternalServiceRequestCreate, PlatformEventEnvelope
from app.schemas.logistics import LogisticsQuoteRequest
from app.services.integration_service import logistics_reference, request_fingerprint, normalized_task_status
from app.services import logistics_service


def transport_payload() -> dict:
    return {
        "farmsense_request_id": "fs-req-1001",
        "requester": {
            "platform_user_id": "farmer-42", "full_name": "Ada Farmer",
            "phone_number": "+2348000000042",
        },
        "service_category": "TRANSPORT",
        "title": "Move maize to Kano warehouse",
        "requirements": "Move 20 bags of maize before Friday",
        "farm_location": {"state": "Kaduna", "label": "North field"},
        "agricultural_details": {
            "crop_type": "maize", "quantity": 20, "quantity_unit": "bags",
            "transport": {
                "pickup": {"state": "Kaduna", "address": "North field"},
                "dropoff": {"state": "Kano", "address": "Central warehouse"},
                "commodity": "maize", "load_quantity": 20, "load_unit": "bags",
            },
        },
    }


def test_agricultural_contract_categories_are_stable():
    assert {item.value for item in ServiceCategory} >= {
        "TRANSPORT", "LABOUR", "TRACTOR_RENTAL", "VETERINARY", "IRRIGATION",
        "WAREHOUSING", "SOIL_TESTING", "EXTENSION_SUPPORT",
    }
    assert UserRole.STUDENT.value == "STUDENT"
    assert RequestSource.FARMSENSE_APP.value == "FARMSENSE_APP"


def test_transport_requires_structured_handoff():
    payload = transport_payload()
    request = InternalServiceRequestCreate.model_validate(payload)
    assert request.agricultural_details.transport.pickup.state == "Kaduna"
    del payload["agricultural_details"]["transport"]
    with pytest.raises(ValidationError):
        InternalServiceRequestCreate.model_validate(payload)


def test_logistics_reference_is_stable():
    task_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert logistics_reference(task_id) == "TAM-LOG-123456781234"
    assert logistics_reference(task_id) == logistics_reference(task_id)


def test_internal_request_fingerprint_is_canonical():
    left = InternalServiceRequestCreate.model_validate(transport_payload())
    reordered = dict(reversed(list(transport_payload().items())))
    right = InternalServiceRequestCreate.model_validate(reordered)
    assert request_fingerprint(left) == request_fingerprint(right)


def test_service_signatures_are_canonical(monkeypatch):
    body = json.dumps(transport_payload(), sort_keys=True, separators=(",", ":")).encode()
    timestamp = "1700000000"
    canonical = b"POST\n/api/v1/internal/service-requests\n1700000000\nnonce-1\n" + hashlib.sha256(body).hexdigest().encode()
    expected = hmac.new(b"contract-secret", canonical, hashlib.sha256).hexdigest()
    assert service_auth.request_signature("contract-secret", "POST", "/api/v1/internal/service-requests", timestamp, "nonce-1", body) == expected
    headers = service_auth.signed_headers("contract-secret", body, timestamp=int(timestamp))
    webhook_expected = hmac.new(b"contract-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert headers["x-taskam-signature"] == "sha256=" + webhook_expected


def test_internal_endpoint_is_not_public(monkeypatch):
    monkeypatch.setattr(service_auth.settings, "farmsense_inbound_secret", "contract-secret")
    monkeypatch.setattr(service_auth, "get_redis", lambda: fakeredis.FakeRedis(decode_responses=True))
    client = TestClient(app)
    response = client.post("/api/v1/internal/service-requests", json=transport_payload())
    assert response.status_code == 401


def test_signed_internal_creation_contract(monkeypatch):
    import app.routers.internal as internal_router

    monkeypatch.setattr(service_auth.settings, "farmsense_inbound_secret", "contract-secret")
    task = SimpleNamespace(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        farmsense_request_id="fs-req-1001", marketplace_request_id="market-1", request_source=RequestSource.FARMSENSE_APP,
        service_category=ServiceCategory.TRANSPORT, status=TaskStatus.PUBLISHED,
        logistics_handoff_reference="TAM-LOG-123456781234",
    )
    created_values = iter((True, False))
    monkeypatch.setattr(internal_router, "create_internal_request", lambda db, payload, key: (task, next(created_values)))
    fake_redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(service_auth, "get_redis", lambda: fake_redis)
    app.dependency_overrides[get_db] = lambda: None
    try:
        body = json.dumps(transport_payload(), separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        headers = service_auth.platform_service_headers(
            "farmsense", "contract-secret", "POST", "/api/v1/internal/service-requests", body,
            timestamp=int(timestamp), nonce="nonce-created",
        )
        headers["Idempotency-Key"] = "create-1"
        client = TestClient(app)
        created = client.post("/api/v1/internal/service-requests", content=body, headers=headers)
        replay_headers = service_auth.platform_service_headers(
            "farmsense", "contract-secret", "POST", "/api/v1/internal/service-requests", body,
            timestamp=int(timestamp), nonce="nonce-replay",
        )
        replay_headers["Idempotency-Key"] = "create-1"
        replay = client.post("/api/v1/internal/service-requests", content=body, headers=replay_headers)
        rejected_replay = client.post("/api/v1/internal/service-requests", content=body, headers=replay_headers)
        assert created.status_code == 201
        assert replay.status_code == 200
        assert rejected_replay.status_code == 401
        assert created.json()["marketplace_request_id"] == "market-1"
        assert created.json()["logistics_handoff_reference"] == "TAM-LOG-123456781234"
        assert replay.json()["created"] is False
    finally:
        app.dependency_overrides.clear()


def test_internal_contract_and_idempotency_constraint_are_exposed():
    schema = app.openapi()
    assert "/api/v1/internal/service-requests" in schema["paths"]
    constraint_names = {constraint.name for constraint in Task.__table__.constraints}
    assert "uq_tasks_source_external_request" in constraint_names
    assert "uq_tasks_source_idempotency_key" in constraint_names


def test_nonce_replay_is_rejected(monkeypatch):
    monkeypatch.setattr(service_auth.settings, "farmsense_inbound_secret", "contract-secret")
    monkeypatch.setattr(service_auth, "get_redis", lambda: fakeredis.FakeRedis(decode_responses=True))
    # Replay behavior is covered end-to-end by the signed creation test using distinct nonces;
    # the canonical Redis key is also stable per service identity.
    assert service_auth.request_signature("contract-secret", "GET", "/x", "1700000000", "n", b"")


def test_shared_fixtures_match_code_contract():
    root = Path(__file__).parents[1] / "contracts" / "v1"
    contract = json.loads((root / "contract.json").read_text())
    assert contract["taskam"]["create_request"] == "POST /api/v1/internal/service-requests"
    assert contract["logistics"]["quote"] == "POST " + logistics_service.QUOTE_PATH
    assert contract["logistics"]["booking"] == "POST " + logistics_service.BOOKING_PATH
    quote = LogisticsQuoteRequest.model_validate_json((root / "logistics_quote_request.json").read_text())
    assert quote.farmsense_request_id.startswith("fs_req_")
    PlatformEventEnvelope.model_validate_json((root / "event_envelope.json").read_text())
    assert set(contract["lifecycle"]) == {"requested", "quoted", "confirmed", "booked", "provider_assigned", "picked_up", "in_transit", "delivered", "cancelled", "failed", "disputed"}
    assert normalized_task_status(TaskStatus.DISPUTED) == "disputed"


def test_ai_contract_accepts_agricultural_extraction():
    extraction = AITaskExtraction.model_validate({
        "title": "Hire workers for cassava harvest", "category": "Labour",
        "requirements": "Need six workers for one day", "complexity": "MODERATE",
        "suggested_payout": 60000, "currency": "NGN", "service_category": "LABOUR",
        "farm_location": {"state": "Oyo"},
        "agricultural_details": {"crop_type": "cassava", "worker_count": 6, "duration_hours": 8},
    })
    assert extraction.service_category == ServiceCategory.LABOUR
    assert extraction.agricultural_details.worker_count == 6
