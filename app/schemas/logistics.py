from datetime import datetime
from pydantic import BaseModel


class LogisticsCoordinate(BaseModel):
    lat: float
    lng: float
    address: str | None = None
    h3_cell: str | None = None


class LogisticsTimeWindow(BaseModel):
    start_at: datetime
    end_at: datetime


class LogisticsShipment(BaseModel):
    produce_type: str
    quantity: float
    quantity_unit: str
    weight_kg: float | None = None
    packaging: str
    requires_refrigeration: bool
    cold_chain_min_c: float | None = None
    cold_chain_max_c: float | None = None
    pickup_window: LogisticsTimeWindow
    delivery_window: LogisticsTimeWindow
    handling_notes: str | None = None
    loading_notes: str | None = None


class LogisticsQuoteRequest(BaseModel):
    platform_user_id: str
    farmsense_request_id: str
    marketplace_request_id: str
    idempotency_key: str
    pickup: LogisticsCoordinate
    dropoff: LogisticsCoordinate
    shipment: LogisticsShipment


class LogisticsBookingRequestWire(BaseModel):
    quote_id: str
    idempotency_key: str
