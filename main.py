import sys
import logging
from pathlib import Path

# ensure backend dir is on path
sys.path.insert(0, str(Path(__file__).parent))

# ── Configure root logger ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dataforge.main")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from config import get_settings

from api.auth import router as auth_router
from api.chat import router as chat_router
from api.generator import router as generator_router
from api.health import router as health_router
from api.datasets import router as datasets_router
from api.analytics import router as analytics_router
from api.usage import router as usage_router

settings = get_settings()

app = FastAPI(title="DataForgeAI", version="1.0.0")

# ── Global exception handler ───────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "[UNHANDLED ERROR] %s %s → %s: %s",
        request.method,
        request.url.path,
        type(exc).__name__,
        str(exc)[:500],
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"success": False, "data": None, "error": "Internal server error. Please try again later."},
    )

# CORS
origins = [
    "http://localhost:8080",
    "http://localhost:5173",
    "http://localhost:5174",
]
if settings.FRONTEND_URL not in origins:
    origins.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(generator_router)
app.include_router(health_router)
app.include_router(datasets_router)
app.include_router(analytics_router)
app.include_router(usage_router)


@app.on_event("startup")
def on_startup():
    logger.info("Starting DataForgeAI backend...")

    # ── Validate critical settings ─────────────────────────────────
    if settings.JWT_SECRET == "change-me":
        logger.warning("[CONFIG] JWT_SECRET is still the default 'change-me' — change it in production!")
    if not settings.GROQ_API_KEY:
        logger.warning("[CONFIG] GROQ_API_KEY is empty — Groq LLM calls will fail.")
    if not settings.GITHUB_TOKEN:
        logger.warning("[CONFIG] GITHUB_TOKEN is empty — GitHub Models LLM calls will fail.")
    if not settings.APPWRITE_PROJECT_ID or not settings.APPWRITE_API_KEY:
        logger.warning("[CONFIG] Appwrite credentials missing — using dev fallback (local storage / mock auth).")

    # ── Database ───────────────────────────────────────────────────
    try:
        from database.base import Base
        from database.session import engine
        from database import models  # noqa: ensure models are imported
        Base.metadata.create_all(bind=engine)
        logger.info("[DB] PostgreSQL tables created / verified at %s", settings.DATABASE_HOST)
    except Exception as exc:
        logger.error("[DB] Failed to connect to PostgreSQL at %s:%s — %s: %s",
                     settings.DATABASE_HOST, settings.DATABASE_PORT,
                     type(exc).__name__, exc)

    # ── Redis ──────────────────────────────────────────────────────
    try:
        from rate_limit.redis_client import get_redis
        get_redis().ping()
        logger.info("[REDIS] Connected to Redis at %s:%s", settings.REDIS_HOST, settings.REDIS_PORT)
    except Exception as exc:
        logger.warning("[REDIS] Cannot reach Redis at %s:%s — rate limiting disabled. %s: %s",
                       settings.REDIS_HOST, settings.REDIS_PORT,
                       type(exc).__name__, exc)

    logger.info("DataForgeAI backend ready ✓")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
