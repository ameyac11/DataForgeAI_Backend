"""
DataForgeAI – Full System Reset (Cloud)
========================================
Targets the LIVE cloud services configured in .env:
  • Supabase PostgreSQL  (aws-1-ap-south-1.pooler.supabase.com)
  • Redis Cloud          (redislabs.com GCP Asia-South1)

Drops every table, recreates the schema, and flushes Redis.

Usage (from the backend/ directory):
    python -m Test.reset_system          # interactive confirmation
    python -m Test.reset_system --yes    # skip confirmation
"""

import sys
import os

# Ensure the backend package root is on sys.path so imports work
# when executed directly or via `python -m Test.reset_system`.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
import ssl
import redis
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

# Explicitly load the .env that sits next to config.py in backend/,
# regardless of which directory the script is launched from.
_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=os.path.abspath(_ENV_FILE), override=True)

from config import get_settings
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

# ── Build a dedicated reset engine that forces SSL for Supabase ──────
# The Supabase connection pooler (Transaction mode) requires sslmode=require.
_SUPABASE_URL = (
    f"postgresql://{settings.DATABASE_USER}:{settings.DATABASE_PASSWORD}"
    f"@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"
    f"?sslmode=require"
)
reset_engine = create_engine(
    _SUPABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 15},
)


def _table_names() -> list[str]:
    """Return existing table names via the engine inspector."""
    return inspect(reset_engine).get_table_names()


def reset_database() -> None:
    """Drop all tables and recreate them from the current model definitions."""
    print("\n── Supabase PostgreSQL Reset ───────────────────────")
    print(f"  Host : {settings.DATABASE_HOST}:{settings.DATABASE_PORT}")
    print(f"  DB   : {settings.DATABASE_NAME}  user={settings.DATABASE_USER}")

    existing = _table_names()
    if existing:
        print(f"  Tables to drop : {', '.join(existing)}")
    else:
        print("  No existing tables found.")

    # Drop everything tracked by SQLAlchemy metadata.
    Base.metadata.drop_all(bind=reset_engine)

    # Also drop any leftover tables not tracked by Base.metadata
    # (e.g. alembic_version).
    with reset_engine.begin() as conn:
        remaining = inspect(reset_engine).get_table_names()
        for tbl in remaining:
            conn.execute(text(f'DROP TABLE IF EXISTS "{tbl}" CASCADE'))

    print("  ✓ All tables dropped.")

    # Recreate schema from models.
    Base.metadata.create_all(bind=reset_engine)
    created = _table_names()
    print(f"  ✓ Tables created : {', '.join(created) or '(none)'}")


def reset_redis() -> None:
    """Flush Redis Cloud (FLUSHALL). Uses SSL as required by redislabs.com."""
    print("\n── Redis Cloud Reset ───────────────────────────────")
    print(f"  Host : {settings.REDIS_HOST}:{settings.REDIS_PORT}")

    # Redis Cloud (redislabs.com) endpoints use TLS on all ports.
    # We pass ssl=True and skip hostname verification to stay compatible
    # with the self-signed redislabs.com certificates.
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            ssl=True,
            ssl_cert_reqs=None,
            decode_responses=True,
            socket_connect_timeout=10,
        )
        client.ping()
        before = client.dbsize()
        client.flushall()
        print(f"  ✓ Redis Cloud flushed  (was {before} keys)")
    except redis.AuthenticationError as exc:
        print(f"  ✗ Redis authentication failed: {exc}")
    except redis.ConnectionError as exc:
        print(f"  ✗ Could not connect to Redis Cloud: {exc}")
    except Exception as exc:
        print(f"  ✗ Redis error: {exc}")


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
    parser = argparse.ArgumentParser(description="DataForgeAI cloud system reset")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════╗")
    print("║      DataForgeAI — CLOUD SYSTEM RESET           ║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    print("  ⚠  Targeting LIVE cloud services:")
    print(f"     PostgreSQL : {settings.DATABASE_HOST}:{settings.DATABASE_PORT} / {settings.DATABASE_NAME}")
    print(f"     Redis      : {settings.REDIS_HOST}:{settings.REDIS_PORT}")

    if not args.yes:
        answer = input("\n  ⚠  This will DESTROY all cloud data. Continue? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Aborted.")
            sys.exit(0)

    reset_database()
    reset_redis()
    reset_analytics_sessions()

    print("\n══════════════════════════════════════════════════════")
    print("  ✓ Cloud system reset complete.")
    print("══════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
