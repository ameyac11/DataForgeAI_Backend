import json
import re
from generator import faker_engine
from generator.formatter import format_output, format_as_json, format_as_csv, format_as_sql, format_as_parquet
from generator.prompts import CUSTOM_GEN_USER, CUSTOM_COMPOUND_GEN_USER, CHAT_DOWNLOAD_USER, CHAT_COMPOUND_DOWNLOAD_USER
from generator.prompt_builder import build_system_prompt
from generator.validator import validate_dataset
from llm.router import generate_text
from models import DEFAULT_GEN_MODEL, is_compound
from rate_limit.limiter import check_and_record

MAX_ROWS = 1000
DEFAULT_CHAT_DOWNLOAD_ROWS = 20


def generate_dataset(
    columns: list,
    rows: int,
    fmt: str = "json",
    source: str = "AI",
    context: str = "",
    model_id: str = None,
    data_mode: str = "synthetic",
) -> dict:
    """Unified dataset generation for the custom generator.
    Returns {data, format, rows_generated}."""
    rows = min(max(rows, 1), MAX_ROWS)
    model_id = model_id or DEFAULT_GEN_MODEL

    if source.upper() == "LIBRARY":
        records = faker_engine.generate(columns, rows)
        return format_output(records, columns, fmt, context)

    records = _generate_ai_with_retry(columns, rows, context, model_id, data_mode)
    return format_output(records, columns, fmt, context)


def _generate_ai_with_retry(columns, rows, context, model_id, data_mode, max_retries=1):
    """Generate with validation and one auto-retry on failure."""
    last_exc = None
    for attempt in range(1 + max_retries):
        try:
            records = _generate_ai(columns, rows, context, model_id, data_mode)
        except Exception as exc:
            last_exc = exc
            if attempt == max_retries:
                raise ValueError(f"AI generation failed: {exc}") from exc
            continue

        if not records:
            if attempt == max_retries:
                raise ValueError(
                    f"AI model '{model_id}' returned no data after {attempt + 1} attempt(s). "
                    "Check your column definitions and try again."
                )
            continue

        is_valid, errors, cleaned = validate_dataset(records, columns)
        if is_valid:
            return cleaned if cleaned else records
        if attempt == max_retries:
            raise ValueError(
                f"AI generation produced invalid data after {attempt + 1} attempt(s). "
                f"Validation errors: {'; '.join(errors[:3])}"
            )

    raise ValueError(last_exc or "AI generation failed after retries.")


def _generate_ai(columns: list, rows: int, context: str, model_id: str, data_mode: str = "synthetic") -> list:
    """Single LLM call to generate dataset rows as JSON."""
    try:
        # global rate limit check (INCR-first, no user_id)
        error = check_and_record(model_id)
        if error:
            raise ValueError(error["message"])

        columns_desc = ", ".join(f'{c["name"]} ({c["type"]})' for c in columns)
        context_line = f'Context/Theme: "{context}". All data should match this theme.' if context else ""

        # normalize mode
        normalized_mode = data_mode.lower().replace("-", "_")
        if normalized_mode == "real_time":
            normalized_mode = "realistic"

        # compound models always use live_data (forced by prompt_builder too)
        if is_compound(model_id):
            normalized_mode = "live_data"

        # build system prompt via PromptBuilder
        system_prompt = build_system_prompt("custom_download", normalized_mode, model_id)

        # pick the right user prompt template
        if is_compound(model_id):
            user_prompt = CUSTOM_COMPOUND_GEN_USER.format(
                rows=rows, columns_desc=columns_desc, context_line=context_line,
            )
        else:
            user_prompt = CUSTOM_GEN_USER.format(
                rows=rows, columns_desc=columns_desc, context_line=context_line,
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw = generate_text(messages, model_id, temperature=0.5)
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

        records = _clean_records(records, columns)
        return records[:rows]

    except json.JSONDecodeError as exc:
        raise ValueError(
            f"AI model '{model_id}' returned malformed JSON. Please try again."
        ) from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"AI generation error with model '{model_id}': {exc}") from exc


def generate_dataset_from_chat(
    chat_messages: list,
    fmt: str = "json",
    model_id: str = None,
    data_mode: str = "synthetic",
    default_rows: int = DEFAULT_CHAT_DOWNLOAD_ROWS,
    context: str = "",
) -> dict:
    """Generate dataset from full chat history. LLM decides rows/columns from conversation.
    Returns {data, format, rows_generated}."""
    model_id = model_id or DEFAULT_GEN_MODEL

    # global rate limit
    error = check_and_record(model_id)
    if error:
        raise ValueError(error["message"])

    # normalize mode
    normalized_mode = data_mode.lower().replace("-", "_")
    if normalized_mode == "real_time":
        normalized_mode = "realistic"
    if is_compound(model_id):
        normalized_mode = "live_data"

    # build system prompt via PromptBuilder
    system_prompt = build_system_prompt("chat_download", normalized_mode, model_id)

    # pick user prompt template
    if is_compound(model_id):
        user_prompt = CHAT_COMPOUND_DOWNLOAD_USER.format(default_rows=default_rows)
    else:
        user_prompt = CHAT_DOWNLOAD_USER.format(
            format_name=fmt.upper(), default_rows=default_rows,
        )

    # build messages: system → chat history → download instruction
    llm_messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_messages:
        llm_messages.append({"role": msg["role"], "content": msg["content"]})
    llm_messages.append({"role": "user", "content": user_prompt})

    raw = generate_text(llm_messages, model_id, temperature=0.8)

    # clean response
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        records = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"AI model '{model_id}' returned malformed JSON for chat download. Please try again."
        ) from exc

    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list) or not records:
        raise ValueError(
            f"AI model '{model_id}' returned an empty or invalid dataset. Please try again."
        )

    # infer columns from the first record (LLM decides schema from conversation)
    first_row = records[0]
    inferred_columns = [{"name": k, "type": _basic_type(v)} for k, v in first_row.items()]

    return format_output(records, inferred_columns, fmt, context)


def _basic_type(value) -> str:
    """Minimal type inference from a sample value — only used for format_output."""
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
                val = None

            expected = col_types.get(name, "string")

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
