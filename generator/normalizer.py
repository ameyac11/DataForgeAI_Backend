"""Normalize AI datasets."""

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

# type buckets

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

# force string types
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

# null detection

_NULL_STRINGS = {"null", "none", "n/a", "na", "nan", "nil", "-", "\u2014", "undefined", ""}


def _is_null(value) -> bool:
    # check for null
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in _NULL_STRINGS:
        return True
    return False


# repair json

def repair_json(raw: str) -> str:
    # fix malformed json
    if not raw or not raw.strip():
        return "[]"

    text = raw.strip()

    # strip md fences
    text = re.sub(r"```(?:json|JSON|javascript|JS)?\s*\n?", "", text)
    text = re.sub(r"```\s*$", "", text)

    # strip leading prose
    idx_bracket = text.find("[")
    idx_brace = text.find("{")
    if idx_bracket == -1:
        idx_bracket = len(text)
    if idx_brace == -1:
        idx_brace = len(text)
    first_bracket = min(idx_bracket, idx_brace)
    if 0 < first_bracket < len(text):
        text = text[first_bracket:]

    # strip trailing prose
    last_close = max(text.rfind("]"), text.rfind("}"))
    if last_close != -1:
        text = text[:last_close + 1]

    # rm js comments
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # fix trailing commas
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # fix truncated output
    open_brackets = text.count("[") - text.count("]")
    open_braces = text.count("{") - text.count("}")

    # check unterminated string
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

    # close unclosed brackets
    text += "}" * max(0, open_braces)
    text += "]" * max(0, open_brackets)

    # wrap single object
    text_stripped = text.strip()
    if text_stripped.startswith("{") and not text_stripped.startswith("["):
        try:
            json.loads(text_stripped)
            text = f"[{text_stripped}]"
        except Exception:
            text = f"[{text_stripped}]"

    return text


# date parsing

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
    # parse to iso8601
    if _is_null(value):
        return None

    raw = str(value).strip()

    # handle unix ts
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

    # set output fmt
    if expected_type in ("time", "duration"):
        out_fmt = _TIME_OUTPUT_FMT
    elif expected_type in ("datetime", "timestamp"):
        out_fmt = _DATETIME_OUTPUT_FMT
    else:
        out_fmt = _DATE_OUTPUT_FMT

    # explicit formats
    for fmt in _STRPTIME_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime(out_fmt)
        except ValueError:
            continue

    # fuzzy parse
    if DATEUTIL_AVAILABLE:
        try:
            dt = dateutil_parser.parse(raw, fuzzy=True, dayfirst=False)
            return dt.strftime(out_fmt)
        except (ValueError, OverflowError, TypeError):
            pass

    # extract yyyy-mm-dd
    m = re.search(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", raw)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return dt.strftime(out_fmt)
        except ValueError:
            pass

    # extract mm/dd/yyyy
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", raw)
    if m:
        try:
            dt = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return dt.strftime(out_fmt)
        except ValueError:
            pass

    logger.debug("[NORMALIZER] Could not parse date: '%s'", raw[:80])
    return raw  # return original rather than discarding


# number parsing

_NUMERIC_NOISE = re.compile(r"[^\d.\-eE+]")
_PERCENT_RE = re.compile(r"^[+\-]?\s*[\d,]+\.?\d*\s*%$")
_CURRENCY_RE = re.compile(r"^[\u00a3$\u20ac\u00a5\u20b9\u20bd\u20a9]\s*[\d,]+\.?\d*$")


def _parse_int(value) -> int:
    # coerce to int
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
    # coerce to float
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


# boolean parsing

_TRUTHY = {"true", "yes", "1", "on", "t", "y", "active", "enabled", "available", "open", "approved"}
_FALSY = {"false", "no", "0", "off", "f", "n", "inactive", "disabled", "unavailable", "closed", "rejected"}


def _parse_bool(value) -> bool:
    # coerce to bool
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


# string parsing

def _clean_string(value) -> str:
    # clean string
    if _is_null(value):
        return ""
    s = str(value).strip()
    # Strip surrounding quotes that LLMs sometimes add
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s)
    return s


# type inference

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
    # infer col type
    name_lower = name.lower().strip().replace(" ", "_")

    # name inference
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
    # word boundaries
    if any(kw in name_lower for kw in int_keywords):
        return "Number"
    if re.search(r"(?:^|_)count(?:_|$)", name_lower):
        return "Number"

    # value inference
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


# public api

def normalize_records(records: list, columns: list) -> list:
    # normalize with schema
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


# public inferred api

def normalize_records_inferred(records: list) -> tuple:
    # normalize inferred
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
