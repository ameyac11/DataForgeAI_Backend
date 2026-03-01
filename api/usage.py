"""Usage Status API — returns per-user usage stats for the settings dialog."""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.dependencies import require_auth_cookie
from core.responses import success_response, error_response
from rate_limit.limiter import get_user_usage, USER_DAILY_LIMITS

logger = logging.getLogger("dataforge.api.usage")

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


@router.get("/status")
def get_usage_status(user_id: str = Depends(require_auth_cookie)):
    """Get unified usage status for the current user."""
    try:
        usage = get_user_usage(user_id)
        return success_response(usage)
    except Exception as e:
        logger.error("[USAGE] Failed for user=%s: %s", user_id, e, exc_info=True)
        return error_response("Failed to fetch usage status.", 500)


@router.get("/limits")
def get_usage_limits():
    """Get configured usage limits."""
    return success_response(USER_DAILY_LIMITS)
