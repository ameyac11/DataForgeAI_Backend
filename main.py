import sys
from pathlib import Path

# ensure backend dir is on path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import get_settings

from api.auth import router as auth_router
from api.chat import router as chat_router
from api.generator import router as generator_router
from api.health import router as health_router

settings = get_settings()

app = FastAPI(title="DataForgeAI", version="1.0.0")

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


@app.on_event("startup")
def on_startup():
    # create tables
    from database.base import Base
    from database.session import engine
    from database import models  # noqa: ensure models are imported
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
