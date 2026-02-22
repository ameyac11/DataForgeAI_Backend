import logging
from fastapi import HTTPException
from rate_limit.limiter import check_and_record

logger = logging.getLogger("dataforge.rate_limit")


def enforce_rate_limit(model_id: str):
    """Raise 429 if rate limited. Call before LLM requests."""
    error = check_and_record(model_id)
    if error:
        logger.warning("[RATE LIMIT] Enforced rate limit for model '%s' (type=%s)", model_id, error.get('type'))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for model '{model_id}'. {error['message']}",
        )
