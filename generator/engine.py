import json
import re
from generator import faker_engine
from generator.formatter import format_output, format_as_json, format_as_csv, format_as_sql, format_as_parquet
from generator.prompts import (
    CUSTOM_GEN_SYSTEM, CUSTOM_GEN_USER, CUSTOM_MODE_INSTRUCTIONS,
    CUSTOM_COMPOUND_GEN_SYSTEM, CUSTOM_COMPOUND_GEN_USER,
    CHAT_DOWNLOAD_SYSTEM, CHAT_DOWNLOAD_USER,
    CHAT_COMPOUND_DOWNLOAD_SYSTEM, CHAT_COMPOUND_DOWNLOAD_USER,
    CHAT_MODE_INSTRUCTIONS,
)
from generator.validator import validate_dataset
from llm.router import generate_text, DEFAULT_GEN_MODEL
from rate_limit.limiter import check_rate_limit, record_usage

MAX_ROWS = 1000
DEFAULT_CHAT_DOWNLOAD_ROWS = 20

# Compound models use built-in web tools — no external search needed
COMPOUND_MODELS = {"compound", "compound-mini"}


def generate_dataset(
    columns: list,
    rows: int,
    fmt: str = "json",
    source: str = "AI",
    context: str = "",
    model_id: str = None,
    user_id: str = None,
    data_mode: str = "synthetic",
    use_web_search: bool = False,
) -> dict:
    """Unified dataset generation — used by both custom generator and chat download.
    Returns {data, format, rows_generated}."""
    rows = min(max(rows, 1), MAX_ROWS)
    model_id = model_id or DEFAULT_GEN_MODEL

    if source.upper() == "LIBRARY":
        records = faker_engine.generate(columns, rows)
        return format_output(records, columns, fmt, context)

    # AI mode — try generation with validation retry
    records = _generate_ai_with_retry(columns, rows, context, model_id, user_id, data_mode, use_web_search)
    if not records:
        # fallback to faker
        records = faker_engine.generate(columns, rows)

    return format_output(records, columns, fmt, context)


def _generate_ai_with_retry(columns, rows, context, model_id, user_id, data_mode, use_web_search, max_retries=1):
    """Generate with validation and one auto-retry on failure."""
    for attempt in range(1 + max_retries):
        records = _generate_ai(columns, rows, context, model_id, user_id, data_mode, use_web_search)
        if not records:
            continue

        is_valid, errors, cleaned = validate_dataset(records, columns)
        if is_valid or attempt == max_retries:
            return cleaned if cleaned else records

    return []


def _generate_ai(columns: list, rows: int, context: str, model_id: str, user_id: str, data_mode: str = "synthetic", use_web_search: bool = False) -> list:
    """Single LLM call to generate dataset rows as JSON."""
    try:
        # rate limit check
        if user_id and not check_rate_limit(model_id, user_id):
            return []

        columns_desc = ", ".join(f'{c["name"]} ({c["type"]})' for c in columns)
        context_line = f'Context/Theme: "{context}". All data should match this theme.' if context else ""

        # Normalize mode: map legacy "real-time" to "realistic"
        normalized_mode = data_mode.lower()
        if normalized_mode == "real-time":
            normalized_mode = "realistic"

        is_compound = model_id in COMPOUND_MODELS

        # Compound models: always use live-data mode + compound-specific prompts
        if is_compound:
            normalized_mode = "live-data"
            system_prompt = CUSTOM_COMPOUND_GEN_SYSTEM
            user_prompt = CUSTOM_COMPOUND_GEN_USER.format(
                rows=rows,
                columns_desc=columns_desc,
                context_line=context_line,
            )
        else:
            system_prompt = CUSTOM_GEN_SYSTEM
            mode_instruction = CUSTOM_MODE_INSTRUCTIONS.get(normalized_mode, CUSTOM_MODE_INSTRUCTIONS["synthetic"])
            user_prompt = CUSTOM_GEN_USER.format(
                rows=rows,
                columns_desc=columns_desc,
                context_line=context_line,
                mode_instruction=mode_instruction,
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Compound models get more tokens for web search processing
        if is_compound:
            max_tok = min(rows * 100, 16000)
        else:
            max_tok = min(rows * 60, 8000)

        raw = generate_text(
            messages, model_id,
            temperature=0.5,
            max_tokens=max_tok,
            # Compound models always use web search (handled internally by provider)
            use_web_search=is_compound,
        )
        if not raw:
            return []

        # clean response — strip markdown code blocks
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        records = json.loads(cleaned)
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            return []

        # validate and coerce types
        records = _clean_records(records, columns)

        # record usage on success
        if user_id:
            record_usage(model_id, user_id)

        # fill remaining rows with faker if AI returned fewer
        # BUT NOT for compound models — faker would add garbage to live data
        if len(records) < rows and not is_compound:
            remaining = faker_engine.generate(columns, rows - len(records))
            records.extend(remaining)

        return records[:rows]

    except (json.JSONDecodeError, Exception):
        return []


def generate_dataset_from_chat(
    chat_messages: list,
    fmt: str = "json",
    model_id: str = None,
    user_id: str = None,
    data_mode: str = "synthetic",
    default_rows: int = DEFAULT_CHAT_DOWNLOAD_ROWS,
    context: str = "",
) -> dict:
    """Generate dataset by passing full chat history to the LLM.
    The LLM reads the conversation and generates the exact rows/columns
    the user asked for. Returns {data, format, rows_generated}."""
    model_id = model_id or DEFAULT_GEN_MODEL
    is_compound = model_id in COMPOUND_MODELS

    # rate limit
    if user_id and not check_rate_limit(model_id, user_id):
        return {"data": [], "format": fmt, "rows_generated": 0}

    # Normalize mode
    normalized_mode = data_mode.lower()
    if normalized_mode == "real-time":
        normalized_mode = "realistic"
    if is_compound:
        normalized_mode = "live-data"

    # Pick the right system + user prompts
    if is_compound:
        system_prompt = CHAT_COMPOUND_DOWNLOAD_SYSTEM.format(default_rows=default_rows)
        user_prompt = CHAT_COMPOUND_DOWNLOAD_USER.format(default_rows=default_rows)
    else:
        mode_instruction = CHAT_MODE_INSTRUCTIONS.get(normalized_mode, CHAT_MODE_INSTRUCTIONS["synthetic"])
        system_prompt = CHAT_DOWNLOAD_SYSTEM.format(default_rows=default_rows)
        user_prompt = CHAT_DOWNLOAD_USER.format(
            format_name=fmt.upper(),
            default_rows=default_rows,
            mode_instruction=mode_instruction,
        )

    # Build messages: system → chat history → download instruction
    llm_messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_messages:
        llm_messages.append({"role": msg["role"], "content": msg["content"]})
    llm_messages.append({"role": "user", "content": user_prompt})

    # More tokens for compound models (web search overhead)
    max_tok = 8000 if is_compound else 8000

    raw = generate_text(
        llm_messages, model_id,
        temperature=0.8,
        max_tokens=max_tok,
        use_web_search=is_compound,
    )

    if not raw:
        return {"data": [], "format": fmt, "rows_generated": 0}

    # Clean response
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        records = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"data": [], "format": fmt, "rows_generated": 0}

    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list) or not records:
        return {"data": [], "format": fmt, "rows_generated": 0}

    # Record usage
    if user_id:
        record_usage(model_id, user_id)

    # Infer columns from the records themselves (since LLM decides schema)
    first_row = records[0]
    inferred_columns = [{"name": k, "type": _infer_col_type(k, v)} for k, v in first_row.items()]

    # Format output using inferred columns
    return format_output(records, inferred_columns, fmt, context)


def _infer_col_type(name: str, value) -> str:
    """Quick column type inference from a key name and sample value."""
    n = name.lower()
    if "id" == n or n.endswith("_id") or "rank" in n:
        return "Number"
    if "email" in n:
        return "Email"
    if "price" in n or "cost" in n or "salary" in n or "amount" in n or "revenue" in n or "gdp" in n:
        return "String"  # keep as string — values may have suffixes like "25.4T"
    if "date" in n or "birth" in n:
        return "Date"
    if "rate" in n:
        return "String"  # keep percentages as strings
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, int):
        return "Number"
    if isinstance(value, float):
        return "Number"
    return "String"


def _clean_records(records: list, columns: list) -> list:
    """Validate and coerce each cell to match expected type."""
    col_types = {c["name"]: c["type"].lower() for c in columns}
    cleaned = []

    for row in records:
        if not isinstance(row, dict):
            continue
        clean_row = {}
        for col in columns:
            name = col["name"]
            val = row.get(name)

            if val is None:
                # fill missing with faker
                val = faker_engine.generate_single(name, col["type"], len(cleaned))

            expected = col_types.get(name, "string")

            # coerce numbers
            if expected in ("number", "integer", "int"):
                try:
                    val = int(str(val).replace("$", "").replace(",", "").split(".")[0])
                except (ValueError, TypeError):
                    val = 0

            elif expected in ("float", "decimal", "currency", "price", "latitude", "longitude"):
                try:
                    val = float(str(val).replace("$", "").replace(",", ""))
                except (ValueError, TypeError):
                    val = 0.0

            elif expected == "boolean":
                if isinstance(val, str):
                    val = val.lower() in ("true", "yes", "1")

            clean_row[name] = val
        cleaned.append(clean_row)

    return cleaned
