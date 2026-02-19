import csv
import io
import json
from decimal import Decimal

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    import base64
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False

# column type → SQL type mapping
SQL_TYPE_MAP = {
    "string": "VARCHAR(255)", "email": "VARCHAR(255)", "name": "VARCHAR(255)",
    "first name": "VARCHAR(255)", "last name": "VARCHAR(255)", "full name": "VARCHAR(255)",
    "city": "VARCHAR(255)", "country": "VARCHAR(255)", "state": "VARCHAR(255)",
    "company name": "VARCHAR(255)", "job title": "VARCHAR(255)", "department": "VARCHAR(255)",
    "username": "VARCHAR(255)", "domain": "VARCHAR(255)", "word": "VARCHAR(255)",
    "color": "VARCHAR(255)", "gender": "VARCHAR(50)", "slug": "VARCHAR(255)",
    "credit card": "VARCHAR(255)", "url": "VARCHAR(255)", "ip address": "VARCHAR(255)",
    "password": "VARCHAR(255)", "image url": "VARCHAR(255)", "mac address": "VARCHAR(255)",
    "address": "TEXT", "paragraph": "TEXT", "sentence": "TEXT", "description": "TEXT",
    "number": "INT", "integer": "INT", "int": "INT", "employee id": "VARCHAR(50)",
    "currency": "DECIMAL(15,2)", "price": "DECIMAL(15,2)", "float": "DECIMAL(15,2)", "decimal": "DECIMAL(15,2)",
    "date": "DATE", "date of birth": "DATE",
    "boolean": "BOOLEAN",
    "latitude": "DECIMAL(10,6)", "longitude": "DECIMAL(10,6)",
    "phone number": "VARCHAR(50)", "ssn": "VARCHAR(50)", "postal code": "VARCHAR(50)", "zip code": "VARCHAR(50)",
    "datetime": "TIMESTAMP", "timestamp": "TIMESTAMP", "time": "TIME",
    "uuid": "VARCHAR(36)", "iban": "VARCHAR(50)", "bitcoin address": "VARCHAR(100)",
    "street": "VARCHAR(255)",
}


def format_as_json(records: list) -> list:
    """Clean up types for JSON serialization."""
    cleaned = []
    for row in records:
        clean_row = {}
        for k, v in row.items():
            if isinstance(v, Decimal):
                clean_row[k] = float(v)
            else:
                clean_row[k] = v
        cleaned.append(clean_row)
    return cleaned


def format_as_csv(records: list, columns: list) -> str:
    if not records:
        return ""
    output = io.StringIO()
    fieldnames = [c["name"] for c in columns] if columns else list(records[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for row in records:
        clean = {}
        for k in fieldnames:
            v = row.get(k, "")
            if v is None:
                v = ""
            if isinstance(v, str):
                v = v.replace("\n", " ").replace("\r", " ")
            clean[k] = v
        writer.writerow(clean)
    return output.getvalue()


def format_as_sql(records: list, columns: list, table_name: str = "generated_data") -> str:
    if not records:
        return ""
    fieldnames = [c["name"] for c in columns] if columns else list(records[0].keys())
    col_types = {}
    for c in columns:
        sql_type = SQL_TYPE_MAP.get(c["type"].lower(), "TEXT")
        col_types[c["name"]] = sql_type

    # CREATE TABLE
    col_defs = ", ".join(f'"{name}" {col_types.get(name, "TEXT")}' for name in fieldnames)
    sql = f'CREATE TABLE "{table_name}" ({col_defs});\n\n'

    # INSERTs
    for row in records:
        values = []
        for name in fieldnames:
            v = row.get(name)
            if v is None:
                values.append("NULL")
            elif isinstance(v, bool):
                values.append("TRUE" if v else "FALSE")
            elif isinstance(v, (int, float, Decimal)):
                values.append(str(v))
            else:
                escaped = str(v).replace("\\", "\\\\").replace("'", "''").replace("\n", "\\n").replace("\r", "\\r")
                values.append(f"'{escaped}'")
        cols = ", ".join(f'"{n}"' for n in fieldnames)
        vals = ", ".join(values)
        sql += f'INSERT INTO "{table_name}" ({cols}) VALUES ({vals});\n'

    return sql


def format_as_parquet(records: list) -> str:
    if not PARQUET_AVAILABLE:
        raise ValueError("pyarrow not installed")
    if not records:
        return ""
    # convert Decimals to float
    cleaned = []
    for row in records:
        cleaned.append({k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()})
    table = pa.Table.from_pylist(cleaned)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def format_output(records: list, columns: list, fmt: str, context: str = "") -> dict:
    """Main dispatcher — returns {data, format, rows_generated}."""
    fmt = fmt.lower().strip()

    if fmt == "json":
        data = format_as_json(records)
    elif fmt == "csv":
        data = format_as_csv(records, columns)
    elif fmt == "sql":
        # derive table name from context
        table_name = _derive_table_name(context)
        data = format_as_sql(records, columns, table_name)
    elif fmt == "parquet":
        data = format_as_parquet(records)
    else:
        data = format_as_json(records)
        fmt = "json"

    return {"data": data, "format": fmt, "rows_generated": len(records)}


def _derive_table_name(context: str) -> str:
    if not context:
        return "generated_data"
    # pick first meaningful word
    for word in ["customer", "employee", "product", "user", "order", "student", "sales", "transaction", "inventory"]:
        if word in context.lower():
            return f"{word}_data"
    # sanitize first few words
    clean = "".join(c if c.isalnum() or c == "_" else "_" for c in context[:30].lower()).strip("_")
    return clean or "generated_data"
