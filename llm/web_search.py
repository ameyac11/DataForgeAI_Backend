"""Google Custom Search integration for real-time data enrichment."""
import httpx
from config import get_settings
from rate_limit.redis_client import get_redis

settings = get_settings()

WEB_SEARCH_DAILY_LIMIT = 10  # per user per day


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


def google_search(query: str, num_results: int = 5) -> list[dict]:
    """
    Perform a Google Custom Search and return simplified results.
    Returns: [{"title": ..., "snippet": ..., "link": ...}, ...]
    """
    if not settings.SEARCH_API_KEY or not settings.SEARCH_ENGINE_ID:
        return []

    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": settings.SEARCH_API_KEY,
            "cx": settings.SEARCH_ENGINE_ID,
            "q": query,
            "num": min(num_results, 10),
        }
        resp = httpx.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("items", []):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
            })
        return results
    except Exception:
        return []


def build_search_context(query: str, user_id: str) -> str:
    """
    Perform web search and build a context string for the LLM.
    Returns empty string if search is unavailable or limit exceeded.
    """
    if not check_web_search_limit(user_id):
        return "[Web search limit reached (10/day). Responding without web data.]"

    results = google_search(query)
    if not results:
        return ""

    record_web_search(user_id)

    # Build context string
    parts = ["[WEB SEARCH RESULTS — use this real-time information to generate accurate, up-to-date data:]"]
    for i, r in enumerate(results, 1):
        parts.append(f"{i}. {r['title']}\n   {r['snippet']}\n   Source: {r['link']}")

    return "\n\n".join(parts)
