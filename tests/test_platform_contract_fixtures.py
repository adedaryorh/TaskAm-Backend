import json
from pathlib import Path


def test_canonical_platform_lifecycle_fixture():
    fixture = json.loads((Path(__file__).parents[1] / "contracts/v1/contract.json").read_text())
    assert fixture["lifecycle"] == [
        "requested", "quoted", "confirmed", "booked", "provider_assigned",
        "picked_up", "in_transit", "delivered", "cancelled", "failed", "disputed",
    ]


def test_canonical_platform_event_envelope_fixture():
    event = json.loads((Path(__file__).parents[1] / "contracts/v1/event_envelope.json").read_text())
    assert set(event) == {
        "event_id", "event_type", "occurred_at", "source", "platform_user_id",
        "farmsense_request_id", "marketplace_request_id", "logistics_delivery_id", "data",
    }
