from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uuid
import sentry_sdk

from app.core.config import settings
from app.core.logging import configure_logging, request_id_var
from app.routers import health, auth, webhooks, tasks, marketplace, payments, deliverables, disputes, admin, internal
from app.services.task_service import InvalidTaskTransition

configure_logging()
if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, traces_sample_rate=0.1)

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["x-request-id"] = request_id
    return response


@app.exception_handler(InvalidTaskTransition)
async def invalid_transition_handler(request: Request, exc: InvalidTaskTransition):
    # An illegal state-machine move is a client conflict, not a server error.
    return JSONResponse(status_code=409, content={"detail": str(exc)})

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
