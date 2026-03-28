import logging
import json
from fastapi import APIRouter, UploadFile, File, Query, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel

from core.responses import success_response, error_response
from core.dependencies import require_auth_cookie
from database.session import get_db
from database.models import AnalyticsRun, now_ist
from analytics.file_loader import load_file
from analytics.session_store import (
    create_session, get_session, delete_session, cleanup_expired,
)
from analytics.engine import (
    dataset_summary, column_analysis, distribution_data,
    correlation_matrix, outlier_detection, timeseries_data, data_preview,
    scatter_data, box_plot_data,
)
from analytics.report_gen import generate_pdf
from rate_limit.limiter import check_analytics_limit, RateLimitError
from llm.router import generate_text
from llm.model_config import DEFAULT_CHAT_MODEL

logger = logging.getLogger("dataforge.api.analytics")

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


class ExplainChartRequest(BaseModel):
    panel: str
    context: dict


def _get_owned_run(db: Session, user_id: str, session_id: str) -> AnalyticsRun | None:
    return (
        db.query(AnalyticsRun)
        .filter(AnalyticsRun.session_id == session_id, AnalyticsRun.user_id == user_id)
        .first()
    )


def _get_owned_session(db: Session, user_id: str, session_id: str):
    run = _get_owned_run(db, user_id, session_id)
    if not run:
        return None, error_response("Session not found", 404, error_code="SESSION_NOT_FOUND")

    session = get_session(session_id)
    if not session:
        if run.state == "active":
            run.state = "expired"
            db.commit()
        return None, error_response("Session expired or not found", 404, error_code="SESSION_EXPIRED")

    run.last_accessed_at = now_ist()
    db.commit()
    return session, None


def _check_limit(user_id: str, endpoint: str):
    try:
        check_analytics_limit(user_id, endpoint)
    except RateLimitError as exc:
        return error_response(str(exc), 429, error_code=exc.error_code)
    return None


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    """Upload a dataset and get a session ID back."""
    cleanup_expired()

    limited = _check_limit(user_id, "upload")
    if limited:
        return limited

    if not file.filename:
        return error_response("No file provided", error_code="INVALID_FILE")

    try:
        content = await file.read()
        df = load_file(content, file.filename)
        session_id = create_session(df, file.filename, len(content))
        summary = dataset_summary(df, file.filename, len(content))

        run = AnalyticsRun(
            user_id=user_id,
            session_id=session_id,
            filename=file.filename,
            file_size_bytes=len(content),
            rows=summary.get("rows", 0),
            columns=summary.get("columns", 0),
            numeric_columns=summary.get("numeric_columns", 0),
            categorical_columns=summary.get("categorical_columns", 0),
            missing_pct=str(summary.get("missing_pct", "0.0")),
            memory_bytes=summary.get("memory_bytes", 0),
            state="active",
        )
        db.add(run)
        db.commit()

        return success_response({"session_id": session_id, "summary": summary})
    except ValueError as e:
        return error_response(str(e), error_code="INVALID_FILE")
    except Exception as e:
        db.rollback()
        logger.error("Upload failed: %s", e, exc_info=True)
        return error_response("Failed to process file. Check format and try again.", error_code="UPLOAD_FAILED")


@router.get("/summary")
async def get_summary(
    session_id: str = Query(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "summary")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err
    return success_response(dataset_summary(session["df"], session["filename"], session["file_size"]))


@router.get("/columns")
async def get_columns(
    session_id: str = Query(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "columns")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err
    return success_response(column_analysis(session["df"]))


@router.get("/distribution")
async def get_distribution(
    session_id: str = Query(...),
    column: str = Query(...),
    bins: int = Query(20),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "distribution")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err
    if column not in session["df"].columns:
        return error_response(f"Column '{column}' not found", error_code="INVALID_COLUMN")
    return success_response(distribution_data(session["df"], column, bins))


@router.get("/correlation")
async def get_correlation(
    session_id: str = Query(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "correlation")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err
    return success_response(correlation_matrix(session["df"]))


@router.get("/scatter")
async def get_scatter(
    session_id: str = Query(...),
    col_x: str = Query(...),
    col_y: str = Query(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "scatter")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err
    df = session["df"]
    if col_x not in df.columns or col_y not in df.columns:
        return error_response("One or both columns not found in dataset", error_code="INVALID_COLUMN")
    return success_response(scatter_data(df, col_x, col_y))


@router.get("/boxplot")
async def get_boxplot(
    session_id: str = Query(...),
    column: str = Query(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "boxplot")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err
    if column not in session["df"].columns:
        return error_response(f"Column '{column}' not found", error_code="INVALID_COLUMN")
    return success_response(box_plot_data(session["df"], column))


@router.get("/outliers")
async def get_outliers(
    session_id: str = Query(...),
    column: str = Query(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "outliers")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err
    if column not in session["df"].columns:
        return error_response(f"Column '{column}' not found", error_code="INVALID_COLUMN")
    return success_response(outlier_detection(session["df"], column))


@router.get("/timeseries")
async def get_timeseries(
    session_id: str = Query(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "timeseries")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err
    return success_response(timeseries_data(session["df"]))


@router.get("/preview")
async def get_preview(
    session_id: str = Query(...),
    page: int = Query(1),
    page_size: int = Query(50),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "preview")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err
    return success_response(data_preview(session["df"], page, min(page_size, 200)))


@router.get("/report")
async def download_report(
    session_id: str = Query(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "report")
    if limited:
        return limited
    session, err = _get_owned_session(db, user_id, session_id)
    if err:
        return err

    try:
        pdf_bytes = generate_pdf(session["df"], session["filename"], session["file_size"])
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="DataForgeAI_Report_{session["filename"]}.pdf"'},
        )
    except Exception as e:
        logger.error("Report generation failed: %s", e, exc_info=True)
        return error_response("Failed to generate report", error_code="REPORT_FAILED")


@router.get("/history")
async def get_history(
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "history")
    if limited:
        return limited

    runs = (
        db.query(AnalyticsRun)
        .filter(AnalyticsRun.user_id == user_id)
        .order_by(AnalyticsRun.created_at.desc())
        .limit(limit)
        .all()
    )
    data = [
        {
            "session_id": run.session_id,
            "filename": run.filename,
            "rows": run.rows,
            "columns": run.columns,
            "numeric_columns": run.numeric_columns,
            "categorical_columns": run.categorical_columns,
            "file_size_bytes": run.file_size_bytes,
            "state": run.state,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "last_accessed_at": run.last_accessed_at.isoformat() if run.last_accessed_at else None,
        }
        for run in runs
    ]
    return success_response(data)


@router.post("/explain")
async def explain_chart(
    req: ExplainChartRequest,
    user_id: str = Depends(require_auth_cookie),
):
    limited = _check_limit(user_id, "explain")
    if limited:
        return limited

    try:
        context_json = json.dumps(req.context, ensure_ascii=True)[:8000]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a senior data analyst. Explain analytics panel data for business users. "
                    "Return concise markdown with sections: Key Signal, Interpretation, Recommended Action. "
                    "Keep under 140 words. Mention caveats if sample size or missing data looks high."
                ),
            },
            {
                "role": "user",
                "content": f"Panel: {req.panel}\nData Context: {context_json}",
            },
        ]
        insight = generate_text(messages, model_id=DEFAULT_CHAT_MODEL, temperature=0.2)
        return success_response({"insight": insight})
    except Exception as e:
        logger.error("Chart explanation failed: %s", e, exc_info=True)
        return error_response("Failed to explain chart", 500, error_code="EXPLAIN_FAILED")


@router.delete("/session")
async def end_session(
    session_id: str = Query(...),
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    limited = _check_limit(user_id, "session_delete")
    if limited:
        return limited

    run = _get_owned_run(db, user_id, session_id)
    if not run:
        return error_response("Session not found", 404, error_code="SESSION_NOT_FOUND")

    delete_session(session_id)
    run.state = "ended"
    db.commit()
    return success_response({"deleted": True})
