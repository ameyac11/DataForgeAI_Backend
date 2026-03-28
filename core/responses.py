from fastapi.responses import JSONResponse


def success_response(data=None):
    return {"success": True, "data": data, "error": None}


def error_response(message: str, status_code: int = 400, error_code: str | None = None, details: dict | None = None):
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "data": None,
            "error": message,
            "error_code": error_code,
            "details": details,
        },
    )
