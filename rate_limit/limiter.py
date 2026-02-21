from datetime import datetime, timezone
from rate_limit.redis_client import get_redis
from models import MODEL_CONFIG


def _seconds_until_midnight() -> int:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight = midnight.replace(day=now.day + 1)
    return int((midnight - now).total_seconds())


def check_and_record(model_id: str) -> dict | None:
    """INCR-first rate limiter. Global per-model limits (not per-user).

    1. INCR the counter
    2. Set TTL if counter == 1 (first request in window)
    3. If counter > limit → DECR back, return error dict
    4. If under limit → return None (success)

    Returns None on success, or error dict on rate limit exceeded.
    """
    cfg = MODEL_CONFIG.get(model_id)
    if not cfg:
        return None  # unknown model, allow through

    rpm_limit = cfg["rpm"]
    rpd_limit = cfg["rpd"]

    try:
        r = get_redis()
        rpm_key = f"model:{model_id}:minute_requests"
        rpd_key = f"model:{model_id}:daily_requests"

        # check RPM first
        rpm_count = r.incr(rpm_key)
        if rpm_count == 1:
            r.expire(rpm_key, 60)
        if rpm_count > rpm_limit:
            r.decr(rpm_key)
            return {
                "error_code": "RATE_LIMIT_EXCEEDED",
                "type": "RPM",
                "model": model_id,
                "message": "Rate limit exceeded for this model. Please wait a moment.",
            }

        # check RPD
        rpd_count = r.incr(rpd_key)
        if rpd_count == 1:
            r.expire(rpd_key, _seconds_until_midnight())
        if rpd_count > rpd_limit:
            r.decr(rpd_key)
            # also roll back the RPM increment since the request won't proceed
            r.decr(rpm_key)
            return {
                "error_code": "RATE_LIMIT_EXCEEDED",
                "type": "RPD",
                "model": model_id,
                "message": "Daily limit reached for this model. Try again tomorrow.",
            }

        return None  # success

    except Exception:
        return None  # redis down, allow through


def get_usage_status() -> dict:
    """Get current global usage for all models."""
    status = {}
    try:
        r = get_redis()
        for model_id, cfg in MODEL_CONFIG.items():
            rpm_count = int(r.get(f"model:{model_id}:minute_requests") or 0)
            rpd_count = int(r.get(f"model:{model_id}:daily_requests") or 0)
            status[model_id] = {
                "rpm_used": rpm_count,
                "rpm_limit": cfg["rpm"],
                "rpd_used": rpd_count,
                "rpd_limit": cfg["rpd"],
            }
    except Exception:
        pass
    return status
