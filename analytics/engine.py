import logging
import numpy as np
import pandas as pd
from typing import Any

logger = logging.getLogger("dataforge.analytics.engine")


def dataset_summary(df: pd.DataFrame, filename: str, file_size: int) -> dict:
    mem = df.memory_usage(deep=True).sum()
    num_cols = df.select_dtypes(include=[np.number]).shape[1]
    cat_cols = df.select_dtypes(include=["object", "category"]).shape[1]
    return {
        "filename": filename,
        "rows": len(df),
        "columns": len(df.columns),
        "numeric_columns": num_cols,
        "categorical_columns": cat_cols,
        "missing_values": int(df.isnull().sum().sum()),
        "missing_pct": round(float(df.isnull().sum().sum()) / max(df.size, 1) * 100, 2),
        "duplicates": int(df.duplicated().sum()),
        "memory_bytes": int(mem),
        "memory_display": _format_bytes(mem),
        "file_size_display": _format_bytes(file_size),
        "dtypes": {col: str(df[col].dtype) for col in df.columns},
    }


def column_analysis(df: pd.DataFrame) -> list[dict]:
    results = []
    for col in df.columns:
        series = df[col]
        info: dict[str, Any] = {
            "name": col,
            "dtype": str(series.dtype),
            "missing": int(series.isnull().sum()),
            "missing_pct": round(float(series.isnull().mean()) * 100, 2),
            "unique": int(series.nunique()),
        }

        if _is_numeric(series):
            info["category"] = "numeric"
            clean = series.dropna()
            info["stats"] = {
                "mean": _safe_float(clean.mean()),
                "median": _safe_float(clean.median()),
                "std": _safe_float(clean.std()),
                "min": _safe_float(clean.min()),
                "max": _safe_float(clean.max()),
                "q25": _safe_float(clean.quantile(0.25)),
                "q75": _safe_float(clean.quantile(0.75)),
                "skew": _safe_float(clean.skew()),
            }
        elif _is_datetime(series):
            info["category"] = "datetime"
            clean = pd.to_datetime(series, errors="coerce").dropna()
            if len(clean) > 0:
                info["stats"] = {
                    "min": str(clean.min()),
                    "max": str(clean.max()),
                    "range_days": int((clean.max() - clean.min()).days),
                }
        else:
            info["category"] = "categorical"
            top = series.value_counts().head(10)
            info["top_values"] = [
                {"value": str(v), "count": int(c)} for v, c in top.items()
            ]

        results.append(info)
    return results


def distribution_data(df: pd.DataFrame, col: str, bins: int = 20) -> dict:
    series = df[col].dropna()
    if _is_numeric(df[col]):
        hist, edges = np.histogram(series, bins=bins)
        return {
            "type": "histogram",
            "column": col,
            "bins": [
                {"range": f"{edges[i]:.2f}-{edges[i+1]:.2f}", "count": int(hist[i])}
                for i in range(len(hist))
            ],
        }
    else:
        counts = series.value_counts().head(15)
        return {
            "type": "bar",
            "column": col,
            "values": [{"label": str(k), "count": int(v)} for k, v in counts.items()],
        }


def correlation_matrix(df: pd.DataFrame) -> dict:
    numeric = df.select_dtypes(include=[np.number])
    if numeric.shape[1] < 2:
        return {"columns": [], "matrix": [], "message": "This dataset does not have enough numeric columns for correlation analysis. At least 2 numeric columns are required."}

    if numeric.shape[1] > 15:
        variances = numeric.var().nlargest(15)
        numeric = numeric[variances.index]

    corr = numeric.corr().round(3)
    return {
        "columns": list(corr.columns),
        "matrix": corr.fillna(0).values.tolist(),
        "message": None,
    }


def scatter_data(df: pd.DataFrame, col_x: str, col_y: str, max_points: int = 500) -> dict:
    """Return scatter plot data for two numeric columns."""
    if not _is_numeric(df[col_x]):
        return {"error": f"'{col_x}' is not a numeric column. Scatter plots require numeric data."}
    if not _is_numeric(df[col_y]):
        return {"error": f"'{col_y}' is not a numeric column. Scatter plots require numeric data."}

    clean = df[[col_x, col_y]].dropna()
    if len(clean) > max_points:
        clean = clean.sample(n=max_points, random_state=42)

    return {
        "col_x": col_x,
        "col_y": col_y,
        "points": [{"x": _safe_float(r[col_x]), "y": _safe_float(r[col_y])} for _, r in clean.iterrows()],
        "count": len(clean),
        "error": None,
    }


def box_plot_data(df: pd.DataFrame, col: str) -> dict:
    """Return box plot statistics for a numeric column."""
    if not _is_numeric(df[col]):
        return {"column": col, "error": f"'{col}' is not a numeric column. Box plots require numeric data."}

    series = df[col].dropna()
    q1 = float(series.quantile(0.25))
    q3 = float(series.quantile(0.75))
    iqr = q3 - q1
    lower_whisker = float(series[series >= q1 - 1.5 * iqr].min())
    upper_whisker = float(series[series <= q3 + 1.5 * iqr].max())
    outlier_vals = series[(series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)]

    return {
        "column": col,
        "min": _safe_float(series.min()),
        "q1": round(q1, 3),
        "median": _safe_float(series.median()),
        "q3": round(q3, 3),
        "max": _safe_float(series.max()),
        "lower_whisker": round(lower_whisker, 3),
        "upper_whisker": round(upper_whisker, 3),
        "outliers": [_safe_float(v) for v in outlier_vals.head(50).tolist()],
        "outlier_count": int(len(outlier_vals)),
        "error": None,
    }


def outlier_detection(df: pd.DataFrame, col: str) -> dict:
    series = df[col].dropna()
    if not _is_numeric(df[col]):
        return {"column": col, "error": f"'{col}' is not a numeric column. Outlier detection requires numeric data."}

    q1 = float(series.quantile(0.25))
    q3 = float(series.quantile(0.75))
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    outliers = series[(series < lower) | (series > upper)]

    return {
        "column": col,
        "q1": round(q1, 3),
        "q3": round(q3, 3),
        "iqr": round(iqr, 3),
        "lower_fence": round(lower, 3),
        "upper_fence": round(upper, 3),
        "outlier_count": int(len(outliers)),
        "outlier_pct": round(float(len(outliers)) / max(len(series), 1) * 100, 2),
        "min": _safe_float(series.min()),
        "max": _safe_float(series.max()),
        "median": _safe_float(series.median()),
        "error": None,
    }


def timeseries_data(df: pd.DataFrame) -> list[dict]:
    results = []
    for col in df.columns:
        if not _is_datetime(df[col]):
            continue
        dates = pd.to_datetime(df[col], errors="coerce").dropna()
        if len(dates) < 2:
            continue
        temp = pd.DataFrame({"date": dates})
        temp["date"] = temp["date"].dt.date
        counts = temp.groupby("date").size().reset_index(name="count")
        counts = counts.sort_values("date")
        if len(counts) > 200:
            counts = counts.tail(200)
        results.append({
            "column": col,
            "data": [{"date": str(r["date"]), "count": int(r["count"])} for _, r in counts.iterrows()],
        })
    return results


def data_preview(df: pd.DataFrame, page: int = 1, page_size: int = 50) -> dict:
    start = (page - 1) * page_size
    end = start + page_size
    subset = df.iloc[start:end]
    return {
        "columns": list(df.columns),
        "rows": subset.fillna("").astype(str).values.tolist(),
        "total_rows": len(df),
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (len(df) + page_size - 1) // page_size),
    }


# helpers

def _is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series)


def _is_datetime(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if series.dtype == object:
        sample = series.dropna().head(20)
        try:
            pd.to_datetime(sample)
            return len(sample) > 0
        except (ValueError, TypeError):
            return False
    return False


def _safe_float(val) -> float:
    try:
        f = float(val)
        if np.isnan(f) or np.isinf(f):
            return 0.0
        return round(f, 3)
    except (ValueError, TypeError):
        return 0.0


def _format_bytes(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"
