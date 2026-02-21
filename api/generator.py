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
from database.session import get_db
from models import MODEL_CONFIG, is_compound

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
    column_count: Optional[int] = 10


@router.post("/preview")
def preview(req: PreviewRequest, user_id: str = Depends(require_auth_cookie)):
    """Generate 5-row preview. Always returns JSON list."""
    if not req.columns:
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
            return error_response(str(exc))
        except Exception as exc:
            return error_response(f"Generation failed: {str(exc)[:300]}")

    return success_response(data)


@router.post("/download")
def download(req: DownloadRequest, user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    """Generate full dataset up to 1000 rows."""
    if not req.columns:
        return error_response("No columns provided")
    if req.rows < 1 or req.rows > MAX_ROWS:
        return error_response(f"Rows must be between 1 and {MAX_ROWS}")

    cols = [{"name": c.name, "type": c.type} for c in req.columns]

    # rate limit check for AI mode (global, no user_id)
    if req.source.upper() == "AI" and req.model_id:
        enforce_rate_limit(req.model_id)

    # normalize mode — compound forces live-data
    data_mode = req.data_mode.lower() if req.data_mode else "synthetic"
    if data_mode == "real-time":
        data_mode = "realistic"
    if req.model_id and is_compound(req.model_id):
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
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"Generation failed: {str(exc)[:300]}")

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

    result = suggest_columns(req.topic, req.available_types, user_id, column_count=req.column_count)
    return success_response(result)
