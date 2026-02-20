from datetime import datetime, timezone
from rate_limit.redis_client import get_redis

# per-model limits
MODEL_LIMITS = {
    "gpt-4.1":       {"rpm": 5,  "rpd": 8},
    "gpt-4o-mini":   {"rpm": 10, "rpd": 25},
    "compound":      {"rpm": 15, "rpd": 100},
    "compound-mini": {"rpm": 15, "rpd": 200},
    "llama-scout-4": {"rpm": 10, "rpd": 20},
    "gpt-oss-120b":  {"rpm": 5,  "rpd": 15},
}


def _seconds_until_midnight() -> int:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight = midnight.replace(day=now.day + 1)
    return int((midnight - now).total_seconds())


def check_rate_limit(model_id: str, user_id: str) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    limits = MODEL_LIMITS.get(model_id)
    if not limits:
        return True

    try:
        r = get_redis()
        rpm_key = f"rpm:{model_id}:{user_id}"
        rpd_key = f"rpd:{model_id}:{user_id}"

        rpm_count = int(r.get(rpm_key) or 0)
        rpd_count = int(r.get(rpd_key) or 0)

        if rpm_count >= limits["rpm"] or rpd_count >= limits["rpd"]:
            return False
        return True
    except Exception:
        return True  # redis down, allow through


def record_usage(model_id: str, user_id: str):
    """Increment usage counters after successful request."""
    try:
        r = get_redis()
        rpm_key = f"rpm:{model_id}:{user_id}"
        rpd_key = f"rpd:{model_id}:{user_id}"

        pipe = r.pipeline()
        pipe.incr(rpm_key)
        pipe.expire(rpm_key, 60)
        pipe.incr(rpd_key)
        pipe.expire(rpd_key, _seconds_until_midnight())
        pipe.execute()
    except Exception:
        pass  # don't break on redis failure


def get_usage_status(user_id: str) -> dict:
    """Get current usage for all models."""
    status = {}
    try:
        r = get_redis()
        for model_id, limits in MODEL_LIMITS.items():
            rpm_count = int(r.get(f"rpm:{model_id}:{user_id}") or 0)
            rpd_count = int(r.get(f"rpd:{model_id}:{user_id}") or 0)
            status[model_id] = {
                "rpm_used": rpm_count,
                "rpm_limit": limits["rpm"],
                "rpd_used": rpd_count,
                "rpd_limit": limits["rpd"],
            }
    except Exception:
        pass
    return status
