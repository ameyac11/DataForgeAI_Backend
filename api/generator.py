import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from core.dependencies import require_auth_cookie
from core.responses import success_response, error_response
from generator.engine import generate_dataset, MAX_ROWS
from generator import faker_engine
from generator.columns import suggest_columns
from rate_limit.dependencies import enforce_rate_limit
from rate_limit.limiter import check_dataset_limit, RateLimitError
from database.session import get_db
from llm.model_config import MODEL_CONFIG, is_compound_model

logger = logging.getLogger("dataforge.api.generator")

router = APIRouter(prefix="/api/v1/generate", tags=["generator"])


class Column(BaseModel):
    name: str
    type: str


class PreviewRequest(BaseModel):
    columns: list[Column]
    source: str = "AI"
    context: str = ""
    model_id: Optional[str] = None
    data_mode: str = "synthetic"


class DownloadRequest(BaseModel):
    columns: list[Column]
    rows: int = 100
    format: str = "json"
    source: str = "AI"
    context: str = ""
    model_id: Optional[str] = None
    data_mode: str = "synthetic"
    dataset_name: Optional[str] = None


class ColumnSuggestRequest(BaseModel):
    topic: str
    available_types: list[str]
    column_count: Optional[int] = None


@router.post("/preview")
def preview(req: PreviewRequest, user_id: str = Depends(require_auth_cookie)):
    """Generate 5-row preview. Always returns JSON list."""
    if not req.columns:
        logger.warning("[PREVIEW] Empty columns list from user '%s'", user_id)
        return error_response("No columns provided")

    cols = [{"name": c.name, "type": c.type} for c in req.columns]

    if req.source.upper() == "LIBRARY":
        data = faker_engine.generate(cols, 5)
    else:
        try:
            result = generate_dataset(
                columns=cols, rows=5, fmt="json",
                source=req.source, context=req.context,
                model_id=req.model_id,
                data_mode=req.data_mode,
            )
            data = result["data"]
        except ValueError as exc:
            logger.warning("[PREVIEW] Validation error: %s", exc)
            return error_response(str(exc))
        except Exception as exc:
            logger.error("[PREVIEW] Generation failed (model=%s): %s: %s",
                         req.model_id, type(exc).__name__, exc)
            error_msg = str(exc)[:300]
            if "rate limit" in error_msg.lower():
                return error_response(f"Rate limit exceeded. Please wait a moment and try again.", 429)
            if "authentication" in error_msg.lower():
                return error_response("LLM authentication error. Please contact support.", 503)
            return error_response(f"Preview generation failed. Please try again.")

    return success_response(data)


@router.post("/download")
def download(req: DownloadRequest, user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    """Generate full dataset up to 1000 rows."""
    if not req.columns:
        logger.warning("[DOWNLOAD] Empty columns list from user '%s'", user_id)
        return error_response("No columns provided")
    if req.rows < 1 or req.rows > MAX_ROWS:
        logger.warning("[DOWNLOAD] Invalid row count %d from user '%s'", req.rows, user_id)
        return error_response(f"Rows must be between 1 and {MAX_ROWS}")

    # per-user daily dataset limit
    try:
        check_dataset_limit(user_id)
    except RateLimitError as exc:
        logger.warning("[DOWNLOAD] User '%s' hit daily dataset limit", user_id)
        return error_response(str(exc), 429)

    cols = [{"name": c.name, "type": c.type} for c in req.columns]

    # rate limit check for AI mode (global, no user_id)
    if req.source.upper() == "AI" and req.model_id:
        enforce_rate_limit(req.model_id)

    # normalize mode — compound forces live-data
    data_mode = req.data_mode.lower() if req.data_mode else "synthetic"
    if data_mode == "real-time":
        data_mode = "realistic"
    if req.model_id and is_compound_model(req.model_id):
        data_mode = "live-data"

    result = None
    try:
        result = generate_dataset(
            columns=cols, rows=req.rows, fmt=req.format,
            source=req.source, context=req.context,
            model_id=req.model_id,
            data_mode=data_mode,
        )
    except ValueError as exc:
        logger.warning("[DOWNLOAD] Generation error: %s", exc)
        return error_response(str(exc))
    except Exception as exc:
        logger.error("[DOWNLOAD] Generation failed (model=%s, rows=%d, fmt=%s): %s: %s",
                     req.model_id, req.rows, req.format, type(exc).__name__, exc)
        error_msg = str(exc)[:300]
        if "rate limit" in error_msg.lower():
            return error_response("Rate limit exceeded. Please wait a moment and try again.", 429)
        if "authentication" in error_msg.lower():
            return error_response("LLM authentication error. Please contact support.", 503)
        if "timeout" in error_msg.lower():
            return error_response("Model timed out. Please try again.", 504)
        return error_response("Dataset generation failed. Please try again.")

    # Auto-save dataset
    from api.datasets import auto_save_dataset
    dataset_name = req.dataset_name or (req.context[:100] if req.context else "Generated Dataset")
    save_result = auto_save_dataset(
        user_id=user_id,
        data=result["data"],
        fmt=result["format"],
        dataset_name=dataset_name,
        model_id=req.model_id or "unknown",
        data_mode=data_mode,
        db=db,
    )

    # Flatten: put formatted content directly in "data", metadata at top level
    return {
        "success": True,
        "data": result["data"],
        "format": result["format"],
        "rows_generated": result["rows_generated"],
        "error": None,
        **save_result,
    }


@router.post("/columns")
def columns(req: ColumnSuggestRequest, user_id: str = Depends(require_auth_cookie)):
    """AI-powered column suggestion for a topic."""
    if not req.topic:
        return error_response("Topic is required")
    if not req.available_types:
        return error_response("Available types required")

    try:
        result = suggest_columns(req.topic, req.available_types, user_id, column_count=req.column_count)
        return success_response(result)
    except Exception as exc:
        logger.error("[COLUMNS] Column suggestion failed for topic '%s': %s: %s",
                     req.topic, type(exc).__name__, exc)
        return error_response("Column suggestion failed. Please try again.")
