from fastapi import HTTPException
from rate_limit.limiter import check_and_record


def enforce_rate_limit(model_id: str):
    """Raise 429 if rate limited. Call before LLM requests."""
    error = check_and_record(model_id)
    if error:
        raise HTTPException(status_code=429, detail=error["message"])
