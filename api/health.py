from fastapi import APIRouter
from core.responses import success_response

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    """Basic health check."""
    status = {"status": "healthy", "database": "unknown", "redis": "unknown"}

    # check db
    try:
        from sqlalchemy import text
        from database.session import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["database"] = "connected"
    except Exception:
        status["database"] = "disconnected"

    # check redis
    try:
        from rate_limit.redis_client import get_redis
        get_redis().ping()
        status["redis"] = "connected"
    except Exception:
        status["redis"] = "disconnected"

    return success_response(status)
