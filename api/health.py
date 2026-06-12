import logging
from fastapi import APIRouter
from core.responses import success_response

logger = logging.getLogger("dataforge.api.health")

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    # basic health check
    status = {"status": "healthy", "database": "unknown", "redis": "unknown"}

    # check database
    try:
        from sqlalchemy import text
        from database.session import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        status["database"] = "connected"
    except Exception as e:
        status["database"] = "disconnected"
        logger.warning("[HEALTH] PostgreSQL health check failed: %s: %s", type(e).__name__, e)

    # check redis db
    try:
        from rate_limit.redis_client import get_redis
        get_redis().ping()
        status["redis"] = "connected"
    except Exception as e:
        status["redis"] = "disconnected"
        logger.warning("[HEALTH] Redis health check failed: %s: %s", type(e).__name__, e)

    return success_response(status)
