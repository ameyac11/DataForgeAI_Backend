"""Industry-standard output normalizer for AI-generated datasets.

Instead of rejecting data on format mismatches, this module robustly
parses and coerces every cell to the expected type.  It handles:

- Dates    — 30+ strptime patterns + python-dateutil fuzzy -> ISO 8601
- Numbers  — strips currency symbols, commas, units -> int / float
- Booleans — recognises yes/no/true/false/on/off/1/0/active/...
- Strings  — trim, collapse whitespace, strip stray quotes
- JSON repair — fixes common LLM output issues (trailing commas, etc.)
- Null handling — "null", "none", "N/A", "" -> type-appropriate default
- Smart type inference — infers column types from sample values

Public API
----------
normalize_records(records, columns)          -> list[dict]
normalize_records_inferred(records)          -> tuple[list[dict], list[dict]]
repair_json(raw_text)                        -> str
"""

import json
import logging
import re
from datetime import datetime

try:
    from dateutil import parser as dateutil_parser
    DATEUTIL_AVAILABLE = True
except ImportError:
    DATEUTIL_AVAILABLE = False

logger = logging.getLogger("dataforge.generator.normalizer")

# =====================================================================
# TYPE BUCKETS
# =====================================================================

NUMERIC_INT_TYPES = {
    "number", "integer", "int", "age", "id", "rank",
    "count", "quantity", "qty", "year", "population",
    "employee id", "student id", "order id",
}

NUMERIC_FLOAT_TYPES = {
    "float", "decimal", "currency", "price", "cost", "revenue",
    "salary", "income", "amount", "balance", "weight", "height",
    "latitude", "longitude", "percentage", "rate", "score",
    "rating", "gpa", "temperature", "distance", "area",
}

BOOLEAN_TYPES = {"boolean", "bool", "is_active", "active", "status_flag"}

DATE_TYPES = {
    "date", "datetime", "timestamp", "date of birth", "dob",
    "created_at", "updated_at", "start_date", "end_date",
    "hire_date", "birth_date", "expiry_date", "deadline",
}

TIME_TYPES = {"time", "duration"}

# Types that should stay as strings even if they look numeric
STRING_FORCE_TYPES = {
    "string", "text", "name", "first name", "last name", "full name",
    "email", "phone", "phone number", "address", "street", "city",
    "state", "country", "zip code", "postal code", "company",
    "company name", "job title", "department", "username", "domain",
    "url", "ip address", "mac address", "password", "description",
    "paragraph", "sentence", "word", "color", "gender", "slug",
    "credit card", "ssn", "iban", "bitcoin address", "uuid",
    "image url", "category", "tag", "label", "title", "status",
}

# =====================================================================
# NULL DETECTION
# =====================================================================

_NULL_STRINGS = {"null", "none", "n/a", "na", "nan", "nil", "-", "\u2014", "undefined", ""}


def _is_null(value) -> bool:
    """Check if a value represents null/missing data."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in _NULL_STRINGS:
        return True
    return False


# =====================================================================
# JSON REPAIR - fix common LLM output issues before json.loads
# =====================================================================

def repair_json(raw: str) -> str:
    """Attempt to repair malformed JSON from LLM output.

    Handles:
    - Markdown code fences
    - Leading/trailing non-JSON text
    - Trailing commas before ] or }
    - Truncated output (missing closing brackets)
    - JavaScript-style comments
    """
    if not raw or not raw.strip():
        return "[]"

    text = raw.strip()

    # 1. Strip markdown code fences
    text = re.sub(r"```(?:json|JSON|javascript|JS)?\s*\n?", "", text)
    text = re.sub(r"```\s*$", "", text)

    # 2. Strip leading prose before the first [ or {
    idx_bracket = text.find("[")
    idx_brace = text.find("{")
    if idx_bracket == -1:
        idx_bracket = len(text)
    if idx_brace == -1:
        idx_brace = len(text)
    first_bracket = min(idx_bracket, idx_brace)
    if 0 < first_bracket < len(text):
        text = text[first_bracket:]

    # 3. Strip trailing prose after the last ] or }
    last_close = max(text.rfind("]"), text.rfind("}"))
    if last_close != -1:
        text = text[:last_close + 1]

    # 4. Remove JavaScript-style comments
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # 5. Fix trailing commas:  ,] -> ]  and  ,} -> }
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 6. Fix truncated output - count bracket balance
    open_brackets = text.count("[") - text.count("]")
    open_braces = text.count("{") - text.count("}")

    # Check for unterminated string
    if open_braces > 0 or open_brackets > 0:
        in_string = False
        last_char = ""
        for ch in text:
            if ch == '"' and last_char != "\\":
                in_string = not in_string
            last_char = ch

        if in_string:
            text += '"'
            open_braces = text.count("{") - text.count("}")
            open_brackets = text.count("[") - text.count("]")

    # Close any unclosed braces/brackets
    text += "}" * max(0, open_braces)
    text += "]" * max(0, open_brackets)

    # 7. If the whole thing is a single object, wrap in array
    text_stripped = text.strip()
    if text_stripped.startswith("{") and not text_stripped.startswith("["):
        try:
            json.loads(text_stripped)
            text = f"[{text_stripped}]"
        except Exception:
            text = f"[{text_stripped}]"

    return text


# =====================================================================
# DATE PARSING
# =====================================================================

_STRPTIME_FORMATS = [
    # ISO 8601 variants
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    # US styles
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m-%d-%Y",
    # EU styles
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y",
    # Year-first with slashes
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    # Month name variants
    "%B %d, %Y %H:%M:%S",
    "%B %d, %Y %I:%M %p",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%B %Y",
    "%b %Y",
    # Day-of-week prefixed
    "%A, %B %d, %Y",
    "%a, %b %d, %Y",
    "%a %b %d %Y",
    # Two-digit year
    "%m/%d/%y",
    "%d/%m/%y",
    "%y-%m-%d",
    # Compact
    "%Y%m%d",
    "%Y%m%d%H%M%S",
    # Time only
    "%H:%M:%S",
    "%H:%M",
    "%I:%M:%S %p",
    "%I:%M %p",
]

_DATE_OUTPUT_FMT = "%Y-%m-%d"
_DATETIME_OUTPUT_FMT = "%Y-%m-%dT%H:%M:%S"
_TIME_OUTPUT_FMT = "%H:%M:%S"


def _parse_date(value, expected_type: str = "date") -> str | None:
    """Parse any date-like string to ISO 8601.  Returns original if unparseable."""
    if _is_null(value):
        return None

    raw = str(value).strip()

    # Handle Unix timestamps (seconds or milliseconds)
    if raw.isdigit() and len(raw) >= 8:
        try:
            ts = int(raw)
            if ts > 1e12:  # milliseconds
                ts = ts / 1000
            dt = datetime.utcfromtimestamp(ts)
            out_fmt = _DATETIME_OUTPUT_FMT if expected_type in ("datetime", "timestamp") else _DATE_OUTPUT_FMT
            return dt.strftime(out_fmt)
        except (ValueError, OverflowError, OSError):
            pass

    # Choose output format
    if expected_type in ("time", "duration"):
        out_fmt = _TIME_OUTPUT_FMT
    elif expected_type in ("datetime", "timestamp"):
        out_fmt = _DATETIME_OUTPUT_FMT
    else:
        out_fmt = _DATE_OUTPUT_FMT

    # 1) Explicit strptime formats (fast path)
    for fmt in _STRPTIME_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime(out_fmt)
        except ValueError:
            continue

    # 2) python-dateutil fuzzy parsing
    if DATEUTIL_AVAILABLE:
        try:
            dt = dateutil_parser.parse(raw, fuzzy=True, dayfirst=False)
            return dt.strftime(out_fmt)
        except (ValueError, OverflowError, TypeError):
            pass

    # 3) Regex extraction: find YYYY-MM-DD patterns
    m = re.search(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", raw)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return dt.strftime(out_fmt)
        except ValueError:
            pass

    # 4) Regex extraction: find MM/DD/YYYY patterns
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", raw)
    if m:
        try:
            dt = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return dt.strftime(out_fmt)
        except ValueError:
            pass

    logger.debug("[NORMALIZER] Could not parse date: '%s'", raw[:80])
    return raw  # return original rather than discarding


# =====================================================================
# NUMBER PARSING
# =====================================================================

_NUMERIC_NOISE = re.compile(r"[^\d.\-eE+]")
_PERCENT_RE = re.compile(r"^[+\-]?\s*[\d,]+\.?\d*\s*%$")
_CURRENCY_RE = re.compile(r"^[\u00a3$\u20ac\u00a5\u20b9\u20bd\u20a9]\s*[\d,]+\.?\d*$")


def _parse_int(value) -> int:
    """Best-effort integer coercion."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if _is_null(value):
        return 0
    try:
        s = str(value).strip()
        if _PERCENT_RE.match(s):
            return int(float(s.replace("%", "").replace(",", "").strip()))
        cleaned = _NUMERIC_NOISE.sub("", s)
        if not cleaned or cleaned in ("-", ".", ""):
            return 0
        return int(float(cleaned))
    except (ValueError, TypeError, OverflowError):
        return 0


def _parse_float(value) -> float:
    """Best-effort float coercion."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if _is_null(value):
        return 0.0
    try:
        s = str(value).strip()
        if _PERCENT_RE.match(s):
            return float(s.replace("%", "").replace(",", "").strip())
        cleaned = _NUMERIC_NOISE.sub("", s)
        if not cleaned or cleaned in ("-", ".", ""):
            return 0.0
        return round(float(cleaned), 6)
    except (ValueError, TypeError, OverflowError):
        return 0.0


# =====================================================================
# BOOLEAN PARSING
# =====================================================================

_TRUTHY = {"true", "yes", "1", "on", "t", "y", "active", "enabled", "available", "open", "approved"}
_FALSY = {"false", "no", "0", "off", "f", "n", "inactive", "disabled", "unavailable", "closed", "rejected"}


def _parse_bool(value) -> bool:
    """Best-effort boolean coercion."""
    if isinstance(value, bool):
        return value
    if _is_null(value):
        return False
    s = str(value).strip().lower()
    if s in _TRUTHY:
        return True
    if s in _FALSY:
        return False
    try:
        return bool(float(s))
    except (ValueError, TypeError):
        return False


# =====================================================================
# STRING PARSING
# =====================================================================

def _clean_string(value) -> str:
    """Normalize a string value: trim, collapse whitespace, strip stray quotes."""
    if _is_null(value):
        return ""
    s = str(value).strip()
    # Strip surrounding quotes that LLMs sometimes add
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s)
    return s


# =====================================================================
# SMART TYPE INFERENCE - for chat download where columns aren't typed
# =====================================================================

_DATE_LIKE_NAMES = {
    "date", "datetime", "timestamp", "created_at", "updated_at",
    "start_date", "end_date", "birth_date", "dob", "hire_date",
    "expiry_date", "deadline", "published_at", "released_at",
    "discovery_date", "close_approach_date", "last_seen", "first_seen",
    "registration_date", "join_date", "modified_at", "deleted_at",
    "due_date", "event_date", "launch_date", "founded_date",
}

_BOOL_LIKE_NAMES = {
    "is_active", "active", "enabled", "available", "verified",
    "is_admin", "is_public", "published", "approved", "completed",
    "is_deleted", "has_discount", "in_stock", "is_premium",
}

_ID_LIKE = re.compile(r"(?:^id$|_id$|^rank$|^index$|^no$|^#$|^sr$|^sno$)", re.IGNORECASE)

_DATE_VALUE_RE = re.compile(
    r"^\d{4}[/\-]\d{1,2}[/\-]\d{1,2}"        # YYYY-MM-DD
    r"|^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"     # MM/DD/YYYY or DD/MM/YYYY
    r"|^\w+ \d{1,2},? \d{4}"                   # Month DD, YYYY
    r"|^\d{1,2} \w+ \d{4}"                     # DD Month YYYY
)


def infer_column_type(name: str, sample_values: list) -> str:
    """Infer the best column type from name and sample values."""
    name_lower = name.lower().strip().replace(" ", "_")

    # Name-based inference (highest priority)
    if _ID_LIKE.match(name_lower):
        return "Number"
    if name_lower in _DATE_LIKE_NAMES or "date" in name_lower or "time" in name_lower:
        return "Date"
    if name_lower in _BOOL_LIKE_NAMES:
        return "Boolean"
    if any(kw in name_lower for kw in (
        "price", "cost", "salary", "revenue", "amount",
        "balance", "latitude", "longitude", "rate", "score",
        "rating", "gpa", "weight", "height", "temperature",
        "distance", "area", "percentage",
    )):
        return "Float"
    # Use word-boundary matching to avoid false positives like "country" matching "count"
    int_keywords = ("age", "quantity", "year", "population", "num_", "number_of", "total_")
    # "count" only matches as a standalone word or prefix (e.g. count, count_of) not inside words like "country"
    if any(kw in name_lower for kw in int_keywords):
        return "Number"
    if re.search(r"(?:^|_)count(?:_|$)", name_lower):
        return "Number"

    # Value-based inference
    non_null = [v for v in sample_values if not _is_null(v)]
    if not non_null:
        return "String"

    if all(isinstance(v, bool) for v in non_null):
        return "Boolean"

    if all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        return "Number"

    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "Float"

    # Check if values look like dates
    str_vals = [str(v) for v in non_null[:5]]
    date_matches = sum(1 for s in str_vals if _DATE_VALUE_RE.match(s.strip()))
    if date_matches >= len(str_vals) * 0.6:
        return "Date"

    return "String"


# =====================================================================
# PUBLIC API - normalize with known schema
# =====================================================================

def normalize_records(records: list, columns: list) -> list:
    """Normalize and coerce every cell in *records* to match the column schema.

    - Strips unexpected fields
    - Fills missing fields with type-appropriate defaults
    - Coerces each value to the declared type
    - Never rejects a row -- always returns best-effort data

    Args:
        records: list of dicts from AI/JSON output
        columns: list of {"name": str, "type": str}

    Returns:
        list of cleaned dicts
    """
    if not records or not columns:
        return records or []

    col_map = {c["name"]: c["type"].lower() for c in columns}
    col_names = [c["name"] for c in columns]
    cleaned = []

    for row in records:
        if not isinstance(row, dict):
            continue

        clean_row = {}
        for name in col_names:
            val = row.get(name)
            expected = col_map.get(name, "string")

            if expected in NUMERIC_INT_TYPES:
                clean_row[name] = _parse_int(val) if not _is_null(val) else 0

            elif expected in NUMERIC_FLOAT_TYPES:
                clean_row[name] = _parse_float(val) if not _is_null(val) else 0.0

            elif expected in BOOLEAN_TYPES:
                clean_row[name] = _parse_bool(val) if not _is_null(val) else False

            elif expected in DATE_TYPES:
                clean_row[name] = _parse_date(val, expected) if not _is_null(val) else None

            elif expected in TIME_TYPES:
                clean_row[name] = _parse_date(val, "time") if not _is_null(val) else None

            else:
                clean_row[name] = _clean_string(val)

        cleaned.append(clean_row)

    if cleaned:
        logger.info("[NORMALIZER] Normalized %d rows across %d columns", len(cleaned), len(col_names))

    return cleaned


# =====================================================================
# PUBLIC API - normalize with inferred schema (chat download)
# =====================================================================

def normalize_records_inferred(records: list) -> tuple:
    """Normalize records when no explicit column schema is available.

    Infers column types from names + sample values, then normalizes.

    Args:
        records: list of dicts from AI/JSON output

    Returns:
        (normalized_records, inferred_columns)
        where inferred_columns = [{"name": str, "type": str}, ...]
    """
    if not records:
        return [], []

    first_row = records[0]
    col_names = list(first_row.keys())

    # Sample up to 5 values per column for inference
    sample_size = min(5, len(records))
    inferred_columns = []
    for name in col_names:
        samples = [records[i].get(name) for i in range(sample_size) if name in records[i]]
        col_type = infer_column_type(name, samples)
        inferred_columns.append({"name": name, "type": col_type})

    normalized = normalize_records(records, inferred_columns)

    logger.info("[NORMALIZER] Inferred schema: %s",
                ", ".join(f"{c['name']}({c['type']})" for c in inferred_columns))

    return normalized, inferred_columns
