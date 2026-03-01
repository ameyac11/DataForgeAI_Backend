from datetime import datetime, timezone, timedelta
import logging
from rate_limit.redis_client import get_redis
from llm.model_config import MODEL_CONFIG

logger = logging.getLogger("dataforge.rate_limit")


# ── Global per-user daily limits (applies across all models) ───────────────────
USER_DAILY_LIMITS = {
    "datasets_generated": 50,
    "queries": 50,
}


class RateLimitError(Exception):
    def __init__(self, error_code: str, message: str, model: str = None, suggested_fallback: str = None, limit_type: str = "user"):
        self.error_code = error_code
        self.message = message
        self.model = model
        self.suggested_fallback = suggested_fallback
        self.limit_type = limit_type
        super().__init__(message)


def _seconds_until_midnight() -> int:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight = midnight + timedelta(days=1)
    return max(int((midnight - now).total_seconds()), 1)


# ── Per-user daily query limit ─────────────────────────────────────────────────

def check_query_limit(user_id: str) -> None:
    """Check and increment the user's daily query count."""
    try:
        r = get_redis()
        key = f"usage:queries:{user_id}"
        count = r.get(key)
        if count and int(count) >= USER_DAILY_LIMITS["queries"]:
            raise RateLimitError(
                "QUERY_LIMIT_EXCEEDED",
                f"Daily query limit reached ({USER_DAILY_LIMITS['queries']} queries/day). Try again tomorrow.",
                limit_type="user",
            )
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _seconds_until_midnight())
        pipe.execute()
    except RateLimitError:
        raise
    except Exception as e:
        logger.warning("[RATE LIMIT] Redis error in check_query_limit: %s — allowing through", e)


def check_dataset_limit(user_id: str) -> None:
    """Check and increment the user's daily dataset generation count."""
    try:
        r = get_redis()
        key = f"usage:datasets:{user_id}"
        count = r.get(key)
        if count and int(count) >= USER_DAILY_LIMITS["datasets_generated"]:
            raise RateLimitError(
                "DATASET_LIMIT_EXCEEDED",
                f"Daily dataset generation limit reached ({USER_DAILY_LIMITS['datasets_generated']} datasets/day). Try again tomorrow.",
                limit_type="user",
            )
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _seconds_until_midnight())
        pipe.execute()
    except RateLimitError:
        raise
    except Exception as e:
        logger.warning("[RATE LIMIT] Redis error in check_dataset_limit: %s — allowing through", e)


def get_user_usage(user_id: str) -> dict:
    """Return current usage vs limits for a user."""
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.get(f"usage:datasets:{user_id}")
        pipe.get(f"usage:queries:{user_id}")
        results = pipe.execute()
        return {
            "datasets_generated": {"used": int(results[0]) if results[0] else 0, "limit": USER_DAILY_LIMITS["datasets_generated"]},
            "queries": {"used": int(results[1]) if results[1] else 0, "limit": USER_DAILY_LIMITS["queries"]},
        }
    except Exception as e:
        logger.warning("[RATE LIMIT] Redis error in get_user_usage: %s", e)
        return {
            "datasets_generated": {"used": 0, "limit": USER_DAILY_LIMITS["datasets_generated"]},
            "queries": {"used": 0, "limit": USER_DAILY_LIMITS["queries"]},
        }


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

    except Exception as e:
        logger.warning("[RATE LIMIT] Redis error during rate check for '%s': %s: %s — allowing request through",
                       model_id, type(e).__name__, e)
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
    except Exception as e:
        logger.warning("[RATE LIMIT] Redis error during usage status check: %s: %s", type(e).__name__, e)
    return status
