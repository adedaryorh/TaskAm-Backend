from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.queue import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    get_redis().ping()
    return {"status": "ready", "database": "connected", "redis": "connected"}


@router.get("/health/queues")
def queue_health():
    redis = get_redis()
    return {
        name: {"ready": redis.llen(name), "delayed": redis.zcard(f"{name}:delayed"), "dead": redis.llen(f"{name}:dead")}
        for name in ("whatsapp_messages", "ai_parse_tasks")
    }
