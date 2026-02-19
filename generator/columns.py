import json
import re
from generator.prompts import COLUMN_SUGGEST_SYSTEM, COLUMN_SUGGEST_USER
from llm.router import generate_text

# single model for column suggestion
COLUMN_MODEL = "gpt-4o-mini"


def suggest_columns(topic: str, available_types: list, user_id: str = None) -> list:
    """AI-powered column suggestion. Returns [{"name": ..., "type": ...}]."""
    if not topic or not available_types:
        return []

    try:
        types_str = ", ".join(available_types)
        user_prompt = COLUMN_SUGGEST_USER.format(topic=topic, available_types=types_str)

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

        return valid if valid else _fallback_columns(topic, available_types)

    except Exception:
        return _fallback_columns(topic, available_types)


def _fallback_columns(topic: str, available_types: list) -> list:
    """Sensible defaults when AI fails."""
    cols = []
    topic_clean = topic.lower().replace(" ", "_")

    if "Number" in available_types:
        cols.append({"name": f"{topic_clean}_id", "type": "Number"})
    if "String" in available_types:
        cols.append({"name": "name", "type": "String"})
    if "Date" in available_types:
        cols.append({"name": "created_at", "type": "Date"})

    return cols
