import json
import re
from generator.prompts import COLUMN_SUGGEST_SYSTEM, COLUMN_SUGGEST_USER
from llm.router import generate_text

# single model for column suggestion
COLUMN_MODEL = "gpt-4.1-nano"

# column count limits
DEFAULT_COLUMN_COUNT = 10
MAX_COLUMN_COUNT = 10
MIN_COLUMN_COUNT = 3


def suggest_columns(topic: str, available_types: list, user_id: str = None, column_count: int = None) -> list:
    """AI-powered column suggestion. Returns [{"name": ..., "type": ...}].
    Default: 10 columns. Max: 10 columns regardless of request."""
    if not topic or not available_types:
        return []

    # clamp column count: default 10, max 10
    count = column_count if column_count else DEFAULT_COLUMN_COUNT
    count = min(max(count, MIN_COLUMN_COUNT), MAX_COLUMN_COUNT)

    try:
        types_str = ", ".join(available_types)
        user_prompt = COLUMN_SUGGEST_USER.format(topic=topic, available_types=types_str, column_count=count)

        messages = [
            {"role": "system", "content": COLUMN_SUGGEST_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        raw = generate_text(messages, COLUMN_MODEL, temperature=0.5, max_tokens=1500)
        if not raw:
            return _fallback_columns(topic, available_types)

        # clean markdown
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        # find JSON object
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start == -1 or end == 0:
            return _fallback_columns(topic, available_types)

        parsed = json.loads(cleaned[start:end])
        columns = parsed.get("columns", [])

        # validate
        types_lower = {t.lower() for t in available_types}
        valid = []
        for col in columns:
            name = col.get("name", "").lower().replace(" ", "_")
            ctype = col.get("type", "")
            if ctype.lower() in types_lower and name:
                # match original casing of type
                matched_type = next((t for t in available_types if t.lower() == ctype.lower()), ctype)
                valid.append({"name": name, "type": matched_type})

        # enforce column count limit
        if len(valid) > MAX_COLUMN_COUNT:
            valid = valid[:MAX_COLUMN_COUNT]

        return valid if valid else _fallback_columns(topic, available_types, count)

    except Exception:
        return _fallback_columns(topic, available_types, count)


def _fallback_columns(topic: str, available_types: list, count: int = 10) -> list:
    """Sensible defaults when AI fails. Generates up to `count` columns."""
    cols = []
    topic_clean = topic.lower().replace(" ", "_")

    # base columns
    fallback_pool = [
        (f"{topic_clean}_id", "Number"),
        ("name", "String"),
        ("description", "String"),
        ("category", "String"),
        ("status", "String"),
        ("created_at", "Date"),
        ("amount", "Number"),
        ("email", "Email"),
        ("city", "City"),
        ("notes", "String"),
    ]

    types_lower = {t.lower() for t in available_types}
    for name, ctype in fallback_pool:
        if len(cols) >= count:
            break
        if ctype in available_types or ctype.lower() in types_lower:
            matched = next((t for t in available_types if t.lower() == ctype.lower()), ctype)
            cols.append({"name": name, "type": matched})

    return cols
