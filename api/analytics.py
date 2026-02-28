import logging
from fastapi import APIRouter, UploadFile, File, Query
from fastapi.responses import Response

from core.responses import success_response, error_response
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

logger = logging.getLogger("dataforge.api.analytics")

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a dataset and get a session ID back."""
    cleanup_expired()

    if not file.filename:
        return error_response("No file provided")

    try:
        content = await file.read()
        df = load_file(content, file.filename)
        session_id = create_session(df, file.filename, len(content))
        summary = dataset_summary(df, file.filename, len(content))
        return success_response({"session_id": session_id, "summary": summary})
    except ValueError as e:
        return error_response(str(e))
    except Exception as e:
        logger.error("Upload failed: %s", e, exc_info=True)
        return error_response("Failed to process file. Check format and try again.")


@router.get("/summary")
async def get_summary(session_id: str = Query(...)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)
    return success_response(dataset_summary(session["df"], session["filename"], session["file_size"]))


@router.get("/columns")
async def get_columns(session_id: str = Query(...)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)
    return success_response(column_analysis(session["df"]))


@router.get("/distribution")
async def get_distribution(session_id: str = Query(...), column: str = Query(...), bins: int = Query(20)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)
    if column not in session["df"].columns:
        return error_response(f"Column '{column}' not found")
    return success_response(distribution_data(session["df"], column, bins))


@router.get("/correlation")
async def get_correlation(session_id: str = Query(...)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)
    return success_response(correlation_matrix(session["df"]))


@router.get("/scatter")
async def get_scatter(session_id: str = Query(...), col_x: str = Query(...), col_y: str = Query(...)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)
    df = session["df"]
    if col_x not in df.columns or col_y not in df.columns:
        return error_response("One or both columns not found in dataset")
    return success_response(scatter_data(df, col_x, col_y))


@router.get("/boxplot")
async def get_boxplot(session_id: str = Query(...), column: str = Query(...)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)
    if column not in session["df"].columns:
        return error_response(f"Column '{column}' not found")
    return success_response(box_plot_data(session["df"], column))


@router.get("/outliers")
async def get_outliers(session_id: str = Query(...), column: str = Query(...)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)
    if column not in session["df"].columns:
        return error_response(f"Column '{column}' not found")
    return success_response(outlier_detection(session["df"], column))


@router.get("/timeseries")
async def get_timeseries(session_id: str = Query(...)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)
    return success_response(timeseries_data(session["df"]))


@router.get("/preview")
async def get_preview(session_id: str = Query(...), page: int = Query(1), page_size: int = Query(50)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)
    return success_response(data_preview(session["df"], page, min(page_size, 200)))


@router.get("/report")
async def download_report(session_id: str = Query(...)):
    session = get_session(session_id)
    if not session:
        return error_response("Session expired or not found", 404)

    try:
        pdf_bytes = generate_pdf(session["df"], session["filename"], session["file_size"])
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="DataForgeAI_Report_{session["filename"]}.pdf"'},
        )
    except Exception as e:
        logger.error("Report generation failed: %s", e, exc_info=True)
        return error_response("Failed to generate report")


@router.delete("/session")
async def end_session(session_id: str = Query(...)):
    delete_session(session_id)
    return success_response({"deleted": True})
