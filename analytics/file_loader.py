import io
import sqlite3
import logging
import warnings
import pandas as pd

logger = logging.getLogger("dataforge.analytics.loader")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB limit


def load_csv(content: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(content))


def load_json(content: bytes) -> pd.DataFrame:
    text = content.decode("utf-8")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Mixing dicts with non-Series")
        try:
            df = pd.read_json(io.StringIO(text))
        except ValueError:
            # Fallback: try records orientation or normalize nested JSON
            import json
            data = json.loads(text)
            if isinstance(data, list):
                df = pd.json_normalize(data)
            elif isinstance(data, dict):
                # Try to find the first list value in the dict
                for v in data.values():
                    if isinstance(v, list):
                        df = pd.json_normalize(v)
                        break
                else:
                    df = pd.json_normalize(data)
            else:
                raise ValueError("Unsupported JSON structure")
    return df


def load_parquet(content: bytes) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(content))


def load_sql(content: bytes) -> pd.DataFrame:
    """Parse a .sql file into an in-memory SQLite db, return the largest table."""
    sql_text = content.decode("utf-8")
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(sql_text)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        if not tables:
            raise ValueError("No tables found in SQL file")

        # pick the table with the most rows
        best_table = tables[0]
        best_count = 0
        for t in tables:
            count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if count > best_count:
                best_count = count
                best_table = t

        df = pd.read_sql_query(f'SELECT * FROM "{best_table}"', conn)
        logger.info("Loaded table '%s' with %d rows from SQL", best_table, len(df))
        return df
    finally:
        conn.close()


LOADERS = {
    "csv": load_csv,
    "json": load_json,
    "parquet": load_parquet,
    "sql": load_sql,
}


def load_file(content: bytes, filename: str) -> pd.DataFrame:
    ext = filename.rsplit(".", 1)[-1].lower()
    loader = LOADERS.get(ext)
    if not loader:
        raise ValueError(f"Unsupported file type: .{ext}")
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(f"File too large ({len(content) / 1024 / 1024:.1f} MB). Max is 50 MB.")
    return loader(content)
