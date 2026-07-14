import uuid

from pydantic import BaseModel, Field

from app.models.base import UserRole, ServiceCategory


class MerchantSignupRequest(BaseModel):
    phone_number: str = Field(..., examples=["+2348012345678"])
    password: str = Field(..., min_length=8)
    full_name: str
    business_name: str | None = None
    whatsapp_id: str


class StudentSignupRequest(BaseModel):
    phone_number: str = Field(..., examples=["+2348012345678"])
    email: str | None = None
    password: str = Field(..., min_length=8)
    full_name: str
    school: str | None = None
    skills: str | None = None


class ServiceProviderSignupRequest(BaseModel):
    phone_number: str
    email: str | None = None
    password: str = Field(..., min_length=8)
    full_name: str
    provider_types: list[str] = Field(..., min_length=1)
    service_categories: list[ServiceCategory] = Field(..., min_length=1)


class LoginRequest(BaseModel):
    phone_number: str
    password: str


class MerchantClaimRequest(BaseModel):
    phone_number: str


class MerchantClaimCompleteRequest(BaseModel):
    phone_number: str
    code: str = Field(..., min_length=6, max_length=6)
    password: str = Field(..., min_length=8)
    full_name: str
    business_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: uuid.UUID


class UserResponse(BaseModel):
    id: uuid.UUID
    phone_number: str
    email: str | None
    full_name: str
    role: UserRole
    is_active: bool
    is_verified: bool

    class Config:
        from_attributes = True


class PayoutAccountRequest(BaseModel):
    bank_code: str
    account_number: str = Field(..., min_length=10, max_length=20)
    account_name: str
