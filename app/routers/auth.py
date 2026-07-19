from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import enforce_auth_rate_limit
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    MerchantSignupRequest,
    StudentSignupRequest,
    ServiceProviderSignupRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
    MerchantClaimRequest,
    MerchantClaimCompleteRequest,
    PayoutAccountRequest,
)
from app.services import auth_service
from app.core.deps import require_roles
from app.models.base import UserRole
from app.models.user import Student, ProviderProfile

router = APIRouter(prefix="/auth", tags=["auth"])

# Credential endpoints share one strict per-IP limiter (brute-force / stuffing guard).
_rate_limited = Depends(enforce_auth_rate_limit)


@router.post("/signup/merchant", response_model=TokenResponse, status_code=201, dependencies=[_rate_limited])
def signup_merchant(payload: MerchantSignupRequest, db: Session = Depends(get_db)):
    return auth_service.signup_merchant(db, payload)


@router.post("/signup/student", response_model=TokenResponse, status_code=201, dependencies=[_rate_limited])
def signup_student(payload: StudentSignupRequest, db: Session = Depends(get_db)):
    return auth_service.signup_student(db, payload)


@router.post("/signup/service-provider", response_model=TokenResponse, status_code=201, dependencies=[_rate_limited])
def signup_service_provider(payload: ServiceProviderSignupRequest, db: Session = Depends(get_db)):
    return auth_service.signup_service_provider(db, payload)


@router.post("/login", response_model=TokenResponse, dependencies=[_rate_limited])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    return auth_service.login(db, payload)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/claim-merchant/request", status_code=202, dependencies=[_rate_limited])
def request_merchant_account_claim(payload: MerchantClaimRequest, db: Session = Depends(get_db)):
    auth_service.request_merchant_claim(db, payload.phone_number)
    return {"detail": "If the account is eligible, a code was sent by WhatsApp"}


@router.post("/claim-merchant/complete", response_model=TokenResponse, dependencies=[_rate_limited])
def complete_merchant_account_claim(payload: MerchantClaimCompleteRequest, db: Session = Depends(get_db)):
    return auth_service.complete_merchant_claim(db, payload)


@router.put("/student/payout-account")
def update_payout_account(
    payload: PayoutAccountRequest,
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.SERVICE_PROVIDER)),
    db: Session = Depends(get_db),
):
    student = db.query(Student).filter(Student.user_id == current_user.id).first()
    profile = student or db.query(ProviderProfile).filter(ProviderProfile.user_id == current_user.id).first()
    if profile is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Provider profile not found")
    profile.payout_bank_code = payload.bank_code
    profile.payout_account_number = payload.account_number
    profile.payout_account_name = payload.account_name
    profile.payout_recipient_code = None
    db.commit()
    return {"detail": "Payout account updated"}
