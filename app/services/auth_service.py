from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password, create_access_token
from app.models.base import UserRole
from app.models.user import User, Merchant, Student, ProviderProfile
from app.schemas.auth import MerchantSignupRequest, StudentSignupRequest, ServiceProviderSignupRequest, LoginRequest, TokenResponse, MerchantClaimCompleteRequest
from app.services.queue import get_redis
from app.services.whatsapp_client import send_text_message
import secrets


def signup_merchant(db: Session, payload: MerchantSignupRequest) -> TokenResponse:
    user = User(
        phone_number=payload.phone_number,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.MERCHANT,
    )
    db.add(user)
    try:
        db.flush()  # get user.id without committing yet
        merchant = Merchant(
            user_id=user.id,
            business_name=payload.business_name,
            whatsapp_id=payload.whatsapp_id,
        )
        db.add(merchant)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number or WhatsApp ID already registered")

    db.refresh(user)
    token = create_access_token(subject=str(user.id), role=user.role.value)
    return TokenResponse(access_token=token, role=user.role, user_id=user.id)


def signup_student(db: Session, payload: StudentSignupRequest) -> TokenResponse:
    user = User(
        phone_number=payload.phone_number,
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.STUDENT,
    )
    db.add(user)
    try:
        db.flush()
        student = Student(
            user_id=user.id,
            school=payload.school,
            skills=payload.skills,
        )
        db.add(student)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number or email already registered")

    db.refresh(user)
    token = create_access_token(subject=str(user.id), role=user.role.value)
    return TokenResponse(access_token=token, role=user.role, user_id=user.id)


def signup_service_provider(db: Session, payload: ServiceProviderSignupRequest) -> TokenResponse:
    user = User(
        phone_number=payload.phone_number, email=payload.email,
        password_hash=hash_password(payload.password), full_name=payload.full_name,
        role=UserRole.SERVICE_PROVIDER,
    )
    db.add(user)
    try:
        db.flush()
        db.add(ProviderProfile(
            user_id=user.id,
            provider_types=payload.provider_types,
            service_categories=[category.value for category in payload.service_categories],
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number or email already registered")
    return TokenResponse(access_token=create_access_token(str(user.id), user.role.value), role=user.role, user_id=user.id)


def login(db: Session, payload: LoginRequest) -> TokenResponse:
    user = db.query(User).filter(User.phone_number == payload.phone_number).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone number or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    token = create_access_token(subject=str(user.id), role=user.role.value)
    return TokenResponse(access_token=token, role=user.role, user_id=user.id)


def request_merchant_claim(db: Session, phone_number: str) -> None:
    user = db.query(User).filter(User.phone_number == phone_number, User.role == UserRole.MERCHANT).first()
    if user is None or user.full_name != "WhatsApp Merchant":
        return
    merchant = db.query(Merchant).filter(Merchant.user_id == user.id).first()
    if merchant is None:
        return
    code = f"{secrets.randbelow(1_000_000):06d}"
    get_redis().setex(f"merchant-claim:{phone_number}", 600, code)
    send_text_message(merchant.whatsapp_id, f"Your TaskAm account claim code is {code}. It expires in 10 minutes.")


_CLAIM_CODE_MAX_ATTEMPTS = 5


def complete_merchant_claim(db: Session, payload: MerchantClaimCompleteRequest) -> TokenResponse:
    key = f"merchant-claim:{payload.phone_number}"
    attempts_key = f"merchant-claim-attempts:{payload.phone_number}"
    redis = get_redis()

    # A 6-digit code is brute-forceable without a hard attempt cap: burn the
    # code after a few wrong guesses, forcing a fresh request.
    attempts = redis.incr(attempts_key)
    if attempts == 1:
        redis.expire(attempts_key, 600)
    if attempts > _CLAIM_CODE_MAX_ATTEMPTS:
        redis.delete(key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts — request a new claim code",
        )

    expected = redis.get(key)
    if expected is None or not secrets.compare_digest(expected, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired claim code")
    user = db.query(User).filter(User.phone_number == payload.phone_number, User.role == UserRole.MERCHANT).first()
    if user is None or user.full_name != "WhatsApp Merchant":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account cannot be claimed")
    merchant = db.query(Merchant).filter(Merchant.user_id == user.id).first()
    if merchant is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account cannot be claimed")
    user.password_hash = hash_password(payload.password)
    user.full_name = payload.full_name
    user.is_verified = True
    merchant.business_name = payload.business_name
    db.commit()
    redis.delete(key)
    redis.delete(attempts_key)
    return TokenResponse(access_token=create_access_token(str(user.id), user.role.value), role=user.role, user_id=user.id)
