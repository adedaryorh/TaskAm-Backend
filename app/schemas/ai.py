from pydantic import BaseModel, Field, field_validator
from app.models.base import ServiceCategory
from app.schemas.integration import AgriculturalDetails, GeoLocation


class AITaskExtraction(BaseModel):
    """
    Strict schema every Gemini response must validate against before a task
    is allowed to move past DRAFT/AI_PARSED. If Gemini's output doesn't fit
    this shape, we do NOT create/advance a task on faith — parsing is
    treated as failed and the merchant is notified to retry.
    """

    title: str = Field(..., min_length=3, max_length=255)
    category: str = Field(..., min_length=2, max_length=100)
    requirements: str = Field(..., min_length=3)
    complexity: str = Field(..., pattern="^(SIMPLE|MODERATE|COMPLEX)$")
    suggested_payout: float = Field(..., gt=0)
    currency: str = Field(default="NGN", pattern="^[A-Z]{3}$")
    service_category: ServiceCategory | None = None
    farm_location: GeoLocation | None = None
    agricultural_details: AgriculturalDetails = Field(default_factory=AgriculturalDetails)

    @field_validator("title", "category", "requirements")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v
