"""
DataForgeAI – Full System Reset
================================
Drops every table, recreates the schema, and flushes Redis.

Usage (from the backend/ directory):
    python -m test.reset_system          # interactive confirmation
    python -m test.reset_system --yes    # skip confirmation
"""

import sys
import os

# Ensure the backend package root is on sys.path so imports work
# when executed directly or via `python -m test.reset_system`.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
import redis
from sqlalchemy import inspect, text

from config import get_settings
from database.session import engine
from database.base import Base

# ── Import every model so SQLAlchemy registers them on Base.metadata ──
from database.models import (          # noqa: F401
    User,
    AuthProviderModel,
    Chat,
    DeletedChat,
    Message,
    UserDataset,
)

settings = get_settings()


def _table_names() -> list[str]:
    """Return existing table names via the engine inspector."""
    insp = inspect(engine)
    return insp.get_table_names()


def reset_database() -> None:
    """Drop all tables and recreate them from the current model definitions."""
    print("\n── Database Reset ──────────────────────────────────")
    existing = _table_names()
    if existing:
        print(f"  Tables to drop : {', '.join(existing)}")
    else:
        print("  No existing tables found.")

    # Drop *everything*, including Alembic revision table if present.
    Base.metadata.drop_all(bind=engine)

    # Also drop leftover tables that may not be tracked by Base.metadata
    with engine.begin() as conn:
        remaining = inspect(engine).get_table_names()
        for tbl in remaining:
            conn.execute(text(f'DROP TABLE IF EXISTS "{tbl}" CASCADE'))

    print("  ✓ All tables dropped.")

    # Recreate from models
    Base.metadata.create_all(bind=engine)
    created = _table_names()
    print(f"  ✓ Tables created : {', '.join(created)}")


def reset_redis() -> None:
    """Flush every Redis database (FLUSHALL)."""
    print("\n── Redis Reset ─────────────────────────────────────")
    try:
        client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
        )
        client.ping()
        before = client.dbsize()
        client.flushall()
        print(f"  ✓ Redis flushed  (was {before} keys)")
    except redis.ConnectionError:
        print("  ⚠ Could not connect to Redis – skipping flush.")
    except Exception as exc:
        print(f"  ⚠ Redis error: {exc}")


def reset_analytics_sessions() -> None:
    """Clear the in-memory analytics session store (if importable)."""
    print("\n── Analytics Session Store ──────────────────────────")
    try:
        from analytics.session_store import _sessions  # noqa: WPS433
        count = len(_sessions)
        _sessions.clear()
        print(f"  ✓ Cleared {count} in-memory analytics sessions.")
    except Exception:
        print("  ⚠ Analytics session store not available – skipping.")


def main() -> None:
    parser = argparse.ArgumentParser(description="DataForgeAI full system reset")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════╗")
    print("║        DataForgeAI — FULL SYSTEM RESET          ║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    print(f"  Database : {settings.database_url}")
    print(f"  Redis    : {settings.REDIS_HOST}:{settings.REDIS_PORT}")

    if not args.yes:
        answer = input("\n  ⚠  This will DESTROY all data. Continue? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Aborted.")
            sys.exit(0)

    reset_database()
    reset_redis()
    reset_analytics_sessions()

    print("\n══════════════════════════════════════════════════════")
    print("  ✓ System reset complete.")
    print("══════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
