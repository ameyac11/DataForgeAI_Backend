import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import get_settings

logger = logging.getLogger("dataforge.database")
settings = get_settings()

try:
    engine = create_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
except Exception as exc:
    logger.error("[DB] Failed to create database engine for '%s': %s: %s",
                 settings.DATABASE_HOST, type(exc).__name__, exc)
    raise

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception as exc:
        logger.error("[DB] Database session error: %s: %s", type(exc).__name__, exc)
        db.rollback()
        raise
    finally:
        db.close()
