"""Schema validation layer for generated datasets.

Validates:
- Required fields present in every row
- Data types match column schema
- Date fields in common formats
- Strips unexpected fields silently
- Auto-retries generation once on validation failure
"""

from datetime import datetime

# Column types that map to numeric
NUMERIC_TYPES = {"number", "integer", "int", "float", "decimal", "currency", "price", "latitude", "longitude", "age"}
# Column types that map to boolean
BOOLEAN_TYPES = {"boolean", "bool"}
# Column types that map to date/timestamp
DATE_TYPES = {"date", "datetime", "timestamp"}

# Common date formats to try when validating
COMMON_DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%d-%m-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y/%m/%d",
]


def validate_dataset(records: list, columns: list) -> tuple:
    """
    Validate generated records against the column schema.

    Args:
        records: list of dicts (each row)
        columns: list of {"name": str, "type": str}

    Returns:
        (is_valid: bool, errors: list[str], cleaned_records: list)
    """
    if not records or not columns:
        return False, ["Empty records or columns"], []

    col_names = {c["name"] for c in columns}
    col_types = {c["name"]: c["type"].lower() for c in columns}
    errors = []
    cleaned = []

    for i, row in enumerate(records):
        if not isinstance(row, dict):
            errors.append(f"Row {i + 1}: not a dict, skipping")
            continue

        # strip unexpected fields
        clean_row = {k: v for k, v in row.items() if k in col_names}

        # check required fields
        for col in columns:
            name = col["name"]
            if name not in clean_row or clean_row[name] is None:
                errors.append(f"Row {i + 1}: missing field '{name}'")
                continue

            val = clean_row[name]
            expected = col_types.get(name, "string")

            # type validation
            if expected in NUMERIC_TYPES:
                if not isinstance(val, (int, float)):
                    try:
                        float(str(val).replace("$", "").replace(",", ""))
                    except (ValueError, TypeError):
                        errors.append(f"Row {i + 1}: field '{name}' expected numeric, got '{type(val).__name__}'")

            elif expected in BOOLEAN_TYPES:
                if not isinstance(val, bool) and str(val).lower() not in ("true", "false", "yes", "no", "1", "0"):
                    errors.append(f"Row {i + 1}: field '{name}' expected boolean, got '{val}'")

            elif expected in DATE_TYPES:
                if isinstance(val, str):
                    parsed = False
                    for fmt in COMMON_DATE_FORMATS:
                        try:
                            datetime.strptime(val, fmt)
                            parsed = True
                            break
                        except ValueError:
                            continue
                    if not parsed:
                        errors.append(f"Row {i + 1}: field '{name}' is not a recognized date format")

        cleaned.append(clean_row)

    is_valid = len(errors) == 0
    return is_valid, errors, cleaned


def validate_and_retry(generate_fn, columns: list, max_retries: int = 1, **kwargs):
    """
    Generate dataset, validate, and retry once on failure.

    Args:
        generate_fn: callable that returns list of records
        columns: column schema
        max_retries: number of retries (default 1)
        **kwargs: passed to generate_fn

    Returns:
        list of records (best-effort)
    """
    for attempt in range(1 + max_retries):
        records = generate_fn(**kwargs)
        if not records:
            continue

        is_valid, errors, cleaned = validate_dataset(records, columns)

        if is_valid or attempt == max_retries:
            # return cleaned records (stripped of unexpected fields)
            return cleaned if cleaned else records

    return []
