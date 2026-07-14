import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.base import RequestSource, ServiceCategory, TaskStatus


class PlatformRequester(BaseModel):
    platform_user_id: str = Field(..., min_length=1, max_length=255)
    full_name: str = Field(..., min_length=2, max_length=255)
    phone_number: str = Field(..., min_length=7, max_length=32)
    email: str | None = None


class GeoLocation(BaseModel):
    label: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    address: str | None = None
    state: str | None = None
    local_government_area: str | None = None


class TransportDetails(BaseModel):
    pickup: GeoLocation
    dropoff: GeoLocation
    commodity: str | None = None
    load_quantity: float | None = Field(None, gt=0)
    load_unit: str | None = None
    vehicle_type: str | None = None
    weight_kg: float | None = Field(None, gt=0)
    packaging: str = "bag"
    requires_refrigeration: bool = False
    cold_chain_min_c: float | None = None
    cold_chain_max_c: float | None = None
    pickup_window_start: datetime | None = None
    pickup_window_end: datetime | None = None
    delivery_window_start: datetime | None = None
    delivery_window_end: datetime | None = None
    handling_notes: str | None = None
    loading_notes: str | None = None


class AgriculturalDetails(BaseModel):
    crop_type: str | None = None
    livestock_type: str | None = None
    acreage: float | None = Field(None, gt=0)
    quantity: float | None = Field(None, gt=0)
    quantity_unit: str | None = None
    urgency: str | None = None
    equipment_type: str | None = None
    duration_hours: float | None = Field(None, gt=0)
    worker_count: int | None = Field(None, gt=0)
    transport: TransportDetails | None = None
    additional: dict = Field(default_factory=dict)


class InternalServiceRequestCreate(BaseModel):
    farmsense_request_id: str | None = Field(None, min_length=1, max_length=255)
    external_request_id: str | None = Field(None, min_length=1, max_length=255, description="Deprecated alias")
    requester: PlatformRequester
    service_category: ServiceCategory
    title: str = Field(..., min_length=3, max_length=255)
    requirements: str = Field(..., min_length=3)
    farm_location: GeoLocation | None = None
    agricultural_details: AgriculturalDetails = Field(default_factory=AgriculturalDetails)
    requested_start_at: datetime | None = None
    budget_ngn: float | None = Field(None, gt=0)
    publish_immediately: bool = True

    @model_validator(mode="after")
    def require_transport_handoff_data(self):
        if not self.farmsense_request_id and not self.external_request_id:
            raise ValueError("farmsense_request_id is required")
        if self.farmsense_request_id and self.external_request_id and self.farmsense_request_id != self.external_request_id:
            raise ValueError("farmsense_request_id and deprecated external_request_id must match")
        self.farmsense_request_id = self.farmsense_request_id or self.external_request_id
        if self.service_category == ServiceCategory.TRANSPORT and self.agricultural_details.transport is None:
            raise ValueError("transport details are required for TRANSPORT requests")
        return self


class InternalServiceRequestResponse(BaseModel):
    id: uuid.UUID
    farmsense_request_id: str
    marketplace_request_id: str
    request_source: RequestSource
    service_category: ServiceCategory
    status: TaskStatus
    logistics_handoff_reference: str | None
    created: bool


class LogisticsBookingRequest(BaseModel):
    quote_id: str


class PlatformEventEnvelope(BaseModel):
    event_id: str
    event_type: str
    occurred_at: datetime
    source: str
    platform_user_id: str | None = None
    farmsense_request_id: str | None = None
    marketplace_request_id: str | None = None
    logistics_delivery_id: str | None = None
    data: dict
