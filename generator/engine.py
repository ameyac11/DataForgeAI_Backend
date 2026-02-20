import json
import re
from generator import faker_engine
from generator.formatter import format_output
from generator.prompts import DATASET_GEN_SYSTEM, DATASET_GEN_USER, MODE_INSTRUCTIONS
from generator.validator import validate_dataset
from llm.router import generate_text, DEFAULT_GEN_MODEL
from rate_limit.limiter import check_rate_limit, record_usage

MAX_ROWS = 1000

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

        mode_instruction = MODE_INSTRUCTIONS.get(normalized_mode, MODE_INSTRUCTIONS["synthetic"])

        user_prompt = DATASET_GEN_USER.format(
            rows=rows,
            columns_desc=columns_desc,
            context_line=context_line,
            mode_instruction=mode_instruction,
        )

        # No Perplexity enrichment — compound models use built-in tools via Groq
        # Non-compound models never use web search

        messages = [
            {"role": "system", "content": DATASET_GEN_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        raw = generate_text(
            messages, model_id,
            temperature=0.5,
            max_tokens=min(rows * 60, 8000),
            use_web_search=use_web_search and model_id in COMPOUND_MODELS,
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
        if len(records) < rows:
            remaining = faker_engine.generate(columns, rows - len(records))
            records.extend(remaining)

        return records[:rows]

    except (json.JSONDecodeError, Exception):
        return []


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
