from fastapi import APIRouter, Depends, Response, status, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.service_auth import require_farmsense_service
from app.db.session import get_db
from app.schemas.integration import InternalServiceRequestCreate, InternalServiceRequestResponse, LogisticsBookingRequest
from app.models.task import Task
from app.services import logistics_service
from app.services.integration_service import create_internal_request

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_farmsense_service)])


@router.post("/service-requests", response_model=InternalServiceRequestResponse, status_code=201)
def create_service_request(
    payload: InternalServiceRequestCreate,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255),
    db: Session = Depends(get_db),
):
    task, created = create_internal_request(db, payload, idempotency_key)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return InternalServiceRequestResponse(
        id=task.id,
        farmsense_request_id=task.farmsense_request_id,
        marketplace_request_id=task.marketplace_request_id,
        request_source=task.request_source,
        service_category=task.service_category,
        status=task.status,
        logistics_handoff_reference=task.logistics_handoff_reference,
        created=created,
    )


def _transport_task(db: Session, marketplace_request_id: str) -> Task:
    task = db.query(Task).filter(Task.marketplace_request_id == marketplace_request_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Marketplace request not found")
    return task


@router.post("/service-requests/{marketplace_request_id}/logistics/quotes")
def request_logistics_quotes(
    marketplace_request_id: str,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    return {"quotes": logistics_service.request_quotes(db, _transport_task(db, marketplace_request_id), idempotency_key)}


@router.post("/service-requests/{marketplace_request_id}/logistics/bookings")
def create_logistics_booking(
    marketplace_request_id: str,
    payload: LogisticsBookingRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    return {"booking": logistics_service.book_quote(db, _transport_task(db, marketplace_request_id), payload.quote_id, idempotency_key)}
