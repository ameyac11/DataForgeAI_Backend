from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from core.dependencies import require_auth_cookie
from core.responses import success_response, error_response
from generator.engine import generate_dataset, MAX_ROWS
from generator import faker_engine
from generator.columns import suggest_columns
from rate_limit.dependencies import enforce_rate_limit

router = APIRouter(prefix="/api/v1/generate", tags=["generator"])


class Column(BaseModel):
    name: str
    type: str


class PreviewRequest(BaseModel):
    columns: list[Column]
    source: str = "AI"
    context: str = ""
    model_id: Optional[str] = None


class DownloadRequest(BaseModel):
    columns: list[Column]
    rows: int = 100
    format: str = "json"
    source: str = "AI"
    context: str = ""
    model_id: Optional[str] = None


class ColumnSuggestRequest(BaseModel):
    topic: str
    available_types: list[str]


@router.post("/preview")
def preview(req: PreviewRequest, user_id: str = Depends(require_auth_cookie)):
    """Generate 5-row preview. Always returns JSON list."""
    if not req.columns:
        return error_response("No columns provided")

    cols = [{"name": c.name, "type": c.type} for c in req.columns]

    if req.source.upper() == "LIBRARY":
        data = faker_engine.generate(cols, 5)
    else:
        # use engine with 5 rows
        result = generate_dataset(
            columns=cols, rows=5, fmt="json",
            source=req.source, context=req.context,
            model_id=req.model_id, user_id=user_id,
        )
        data = result["data"]

    return success_response(data)


@router.post("/download")
def download(req: DownloadRequest, user_id: str = Depends(require_auth_cookie)):
    """Generate full dataset up to 1000 rows."""
    if not req.columns:
        return error_response("No columns provided")
    if req.rows < 1 or req.rows > MAX_ROWS:
        return error_response(f"Rows must be between 1 and {MAX_ROWS}")

    cols = [{"name": c.name, "type": c.type} for c in req.columns]

    # rate limit check for AI mode
    if req.source.upper() == "AI" and req.model_id:
        enforce_rate_limit(req.model_id, user_id)

    result = generate_dataset(
        columns=cols, rows=req.rows, fmt=req.format,
        source=req.source, context=req.context,
        model_id=req.model_id, user_id=user_id,
    )

    return success_response(result)


@router.post("/columns")
def columns(req: ColumnSuggestRequest, user_id: str = Depends(require_auth_cookie)):
    """AI-powered column suggestion for a topic."""
    if not req.topic:
        return error_response("Topic is required")
    if not req.available_types:
        return error_response("Available types required")

    result = suggest_columns(req.topic, req.available_types, user_id)
    return success_response(result)
