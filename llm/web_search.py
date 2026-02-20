"""Web search rate limiting utilities.

Compound / Compound Mini models use built-in Groq web_search + visit_website
tools during dataset generation. This module only handles daily rate-limiting
for those searches. Perplexity integration has been removed.
"""
from rate_limit.redis_client import get_redis

WEB_SEARCH_DAILY_LIMIT = 5  # per user per day


def _seconds_until_midnight() -> int:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight = midnight.replace(day=now.day + 1)
    return int((midnight - now).total_seconds())


def check_web_search_limit(user_id: str) -> bool:
    """Returns True if the user can still perform web searches today."""
    try:
        r = get_redis()
        key = f"websearch:{user_id}"
        count = int(r.get(key) or 0)
        return count < WEB_SEARCH_DAILY_LIMIT
    except Exception:
        return True


def record_web_search(user_id: str):
    """Increment the user's daily web search counter."""
    try:
        r = get_redis()
        key = f"websearch:{user_id}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _seconds_until_midnight())
        pipe.execute()
    except Exception:
        pass


def get_web_search_usage(user_id: str) -> dict:
    """Get current web search usage for a user."""
    try:
        r = get_redis()
        key = f"websearch:{user_id}"
        count = int(r.get(key) or 0)
        return {"used": count, "limit": WEB_SEARCH_DAILY_LIMIT}
    except Exception:
        return {"used": 0, "limit": WEB_SEARCH_DAILY_LIMIT}
