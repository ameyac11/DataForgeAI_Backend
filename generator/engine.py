import json
import re
import logging
from generator import faker_engine
from generator.formatter import format_output, format_as_json, format_as_csv, format_as_sql, format_as_parquet
from generator.prompts import CUSTOM_GEN_USER, CUSTOM_COMPOUND_GEN_USER, CHAT_DOWNLOAD_USER, CHAT_COMPOUND_DOWNLOAD_USER
from generator.prompt_builder import build_system_prompt
from generator.normalizer import normalize_records, normalize_records_inferred, repair_json
from llm.router import generate_text
from models import DEFAULT_GEN_MODEL, is_compound
from rate_limit.limiter import check_and_record

logger = logging.getLogger("dataforge.generator.engine")

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

    records = _generate_ai(columns, rows, context, model_id, data_mode)
    if not records:
        raise ValueError(
            f"AI model '{model_id}' returned no data. "
            "Check your column definitions and try again."
        )
    return format_output(records, columns, fmt, context)


def _generate_ai(columns: list, rows: int, context: str, model_id: str, data_mode: str = "synthetic") -> list:
    """Single LLM call to generate dataset rows as JSON."""
    try:
        # global rate limit check (INCR-first, no user_id)
        error = check_and_record(model_id)
        if error:
            logger.warning("[ENGINE] Rate limit hit for model '%s': %s", model_id, error["type"])
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

        logger.info("[ENGINE] Generating %d rows with model '%s' (mode=%s)", rows, model_id, normalized_mode)
        raw = generate_text(messages, model_id, temperature=0.5)
        if not raw:
            logger.warning("[ENGINE] Model '%s' returned empty response", model_id)
            return []

        records = _extract_json(raw, model_id, "ENGINE")
        if not records:
            return []

        # robust normalization — parse and coerce all types
        records = normalize_records(records, columns)
        return records[:rows]
    except ValueError:
        raise
    except Exception as exc:
        logger.error("[ENGINE] AI generation error with model '%s': %s: %s", model_id, type(exc).__name__, exc)
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
        logger.warning("[ENGINE CHAT] Rate limit hit for model '%s': %s", model_id, error["type"])
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

    logger.info("[ENGINE CHAT] Generating from chat (model='%s', mode=%s, default_rows=%d)",
                model_id, normalized_mode, default_rows)
    raw = generate_text(llm_messages, model_id, temperature=0.8)

    records = _extract_json(raw, model_id, "ENGINE CHAT")
    if not records:
        raise ValueError(
            f"AI model '{model_id}' returned an empty or invalid dataset. Please try again."
        )

    # infer types from column names + sample values, then normalize
    records, inferred_columns = normalize_records_inferred(records)

    return format_output(records, inferred_columns, fmt, context)


# ── shared helpers ────────────────────────────────────────────────────

def _extract_json(raw: str, model_id: str, tag: str) -> list:
    """Extract and parse JSON array from raw LLM output.

    Uses repair_json() to fix common issues (trailing commas,
    truncated output, markdown fences, etc.) before parsing.
    Returns list of dicts or raises ValueError.
    """
    if not raw or not raw.strip():
        logger.warning("[%s] Model '%s' returned empty response", tag, model_id)
        return []

    repaired = repair_json(raw)

    try:
        records = json.loads(repaired)
    except json.JSONDecodeError as exc:
        logger.error("[%s] Model '%s' returned malformed JSON (even after repair): %s",
                     tag, model_id, str(exc)[:120])
        raise ValueError(
            f"AI model '{model_id}' returned malformed JSON. Please try again."
        ) from exc

    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        logger.warning("[%s] Model '%s' returned non-list type: %s", tag, model_id, type(records).__name__)
        return []

    return records
