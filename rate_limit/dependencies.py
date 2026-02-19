from fastapi import HTTPException
from rate_limit.limiter import check_rate_limit


def enforce_rate_limit(model_id: str, user_id: str):
    """Raise 429 if rate limited. Call before LLM requests."""
    if not check_rate_limit(model_id, user_id):
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded for {model_id}")
