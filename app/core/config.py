from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "TaskAm Backend"
    environment: str = "development"
    api_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+psycopg://taskam:taskam@localhost:5432/taskam"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    job_max_attempts: int = 5
    job_retry_base_seconds: int = 5
    notification_poll_seconds: int = 5
    notification_max_attempts: int = 8
    webhook_rate_limit: int = 300
    webhook_rate_window_seconds: int = 60

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24h

    # WhatsApp Cloud API
    whatsapp_verify_token: str = "change-me"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_base: str = "https://graph.facebook.com/v20.0"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # OPay
    opay_public_key: str = ""
    opay_secret_key: str = ""
    opay_merchant_id: str = ""
    opay_webhook_secret: str = ""
    opay_base_url: str = "https://sandboxapi.opaycheckout.com"

    # Paystack
    paystack_secret_key: str = ""
    paystack_public_key: str = ""
    paystack_base_url: str = "https://api.paystack.co"
    payment_settlement_enabled: bool = False

    # Which gateway to use when a merchant doesn't specify one explicitly.
    default_payment_provider: str = "OPAY"  # OPAY | PAYSTACK

    # Object storage (R2 / S3 compatible)
    storage_endpoint_url: str = ""
    storage_access_key_id: str = ""
    storage_secret_access_key: str = ""
    storage_bucket: str = "taskam-files"
    storage_region: str = "auto"
    storage_public_base_url: str = ""

    # Presigned URL expiry (seconds)
    presigned_url_expiry: int = 900

    # Optional SMTP delivery.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    sentry_dsn: str = ""

    # FarmSense service integration. Use independent rotation-managed secrets
    # in production; inbound and outbound secrets may differ.
    farmsense_inbound_secret: str = ""
    farmsense_outbound_secret: str = ""
    farmsense_status_webhook_url: str = ""
    service_auth_max_skew_seconds: int = 300
    outbound_webhook_poll_seconds: int = 5
    outbound_webhook_max_attempts: int = 10
    logistics_service_url: str = ""
    logistics_service_secret: str = ""
    logistics_webhook_secret: str = ""
    taskam_service_identity: str = "taskam"
    allow_legacy_farmsense_auth: bool = False

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.environment.lower() == "production":
            weak = {"", "change-me", "change-me-in-production"}
            if self.jwt_secret in weak:
                raise ValueError("JWT_SECRET must be changed in production")
            if not self.database_url:
                raise ValueError("DATABASE_URL is required in production")
            if self.farmsense_status_webhook_url and not self.farmsense_outbound_secret:
                raise ValueError("FARMSENSE_OUTBOUND_SECRET is required when status callbacks are enabled")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
