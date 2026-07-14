from fastapi import FastAPI, Request
import uuid
import sentry_sdk

from app.core.config import settings
from app.core.logging import configure_logging
from app.routers import health, auth, webhooks, tasks, marketplace, payments, deliverables, disputes, admin, internal

configure_logging()
if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, traces_sample_rate=0.1)

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(webhooks.router, prefix=settings.api_prefix)
app.include_router(tasks.router, prefix=settings.api_prefix)
app.include_router(marketplace.router, prefix=settings.api_prefix)
app.include_router(payments.router, prefix=settings.api_prefix)
app.include_router(deliverables.router, prefix=settings.api_prefix)
app.include_router(disputes.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(internal.router, prefix=settings.api_prefix)


@app.get("/")
def root():
    return {"service": settings.app_name, "environment": settings.environment}
