"""Full system reset — drops and recreates all databases.

Usage (from the backend/ directory):
    python -m Test.full_system_reset          # full reset (interactive)
    python -m Test.full_system_reset --yes    # skip confirmation
    python -m Test.full_system_reset --user   # reset a specific user's data only
    python -m Test.full_system_reset --redis  # reset only Redis
    python -m Test.full_system_reset --postgres  # reset only PostgreSQL
"""

import sys
import os
import argparse
from pathlib import Path
from typing import Optional

# Add backend/ to sys.path so imports resolve regardless of launch directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=os.path.abspath(_ENV_FILE), override=True)

import redis as redis_lib
from sqlalchemy import create_engine, inspect, text

from config import get_settings
from database.base import Base
from database.models import (          # noqa: F401 — register all models on Base.metadata
    User,
    AuthProviderModel,
    Chat,
    DeletedChat,
    Message,
    UserDataset,
    AnalyticsRun,
)

settings = get_settings()

# ── Build a dedicated reset engine (forces SSL for Supabase) ──────────────────
_DB_URL = (
    f"postgresql://{settings.DATABASE_USER}:{settings.DATABASE_PASSWORD}"
    f"@{settings.DATABASE_HOST}:{settings.DATABASE_PORT}/{settings.DATABASE_NAME}"
    f"?sslmode=require"
)
reset_engine = create_engine(
    _DB_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 15},
)


# ─── PostgreSQL ───────────────────────────────────────────────────────────────

def reset_postgres() -> None:
    """Drop all tables and recreate them from current model definitions."""
    print("\n── PostgreSQL Reset ─────────────────────────────────")
    print(f"  Host : {settings.DATABASE_HOST}:{settings.DATABASE_PORT}")
    print(f"  DB   : {settings.DATABASE_NAME}  user={settings.DATABASE_USER}")

    existing = inspect(reset_engine).get_table_names()
    if existing:
        print(f"  Tables found : {', '.join(existing)}")
    else:
        print("  No existing tables found.")

    # Drop all tables tracked by SQLAlchemy metadata (use CASCADE to handle dependencies)
    Base.metadata.drop_all(bind=reset_engine)

    # Drop any remaining tables not tracked by Base (e.g. alembic_version)
    with reset_engine.begin() as conn:
        remaining = inspect(reset_engine).get_table_names()
        for tbl in remaining:
            conn.execute(text(f'DROP TABLE IF EXISTS "{tbl}" CASCADE'))
        # Drop enum types so SQLAlchemy can recreate them cleanly
        for enum_type in ("messageerole", "authprovider", "messagerole"):
            conn.execute(text(f"DROP TYPE IF EXISTS {enum_type} CASCADE"))

    print("  ✓ All tables and enum types dropped.")

    Base.metadata.create_all(bind=reset_engine)
    created = inspect(reset_engine).get_table_names()
    print(f"  ✓ Tables recreated : {', '.join(created) or '(none)'}")


# ─── Redis ────────────────────────────────────────────────────────────────────

def _make_redis_client() -> redis_lib.Redis:
    """Build a Redis client with a TLS-first strategy, then fallback to plain TCP."""
    attempts = [
        {"ssl": True, "ssl_cert_reqs": None},
        {"ssl": False, "ssl_cert_reqs": None},
    ]
    last_exc = None
    for mode in attempts:
        try:
            client = redis_lib.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD or None,
                decode_responses=True,
                socket_connect_timeout=10,
                **mode,
            )
            client.ping()
            return client
        except Exception as exc:  # pragma: no cover - network/env dependent
            last_exc = exc
    raise last_exc


def reset_redis() -> None:
    """Flush all Redis keys (FLUSHALL). Uses SSL for Redis Cloud."""
    print("\n── Redis Reset ──────────────────────────────────────")
    print(f"  Host : {settings.REDIS_HOST}:{settings.REDIS_PORT}")

    try:
        client = _make_redis_client()
        before = client.dbsize()
        client.flushall()
        print(f"  ✓ Redis flushed  (was {before} keys)")
    except redis_lib.AuthenticationError as exc:
        print(f"  ✗ Redis authentication failed: {exc}")
    except redis_lib.ConnectionError as exc:
        print(f"  ✗ Could not connect to Redis: {exc}")
    except Exception as exc:
        print(f"  ✗ Redis error: {exc}")


# ─── Analytics sessions ───────────────────────────────────────────────────────

def reset_analytics_sessions() -> None:
    """Clear the in-memory analytics session store (if importable)."""
    print("\n── Analytics Session Store ──────────────────────────")
    try:
        from analytics.session_store import _sessions  # noqa: WPS433
        count = len(_sessions)
        _sessions.clear()
        print(f"  ✓ Cleared {count} in-memory analytics sessions.")
    except Exception:
        print("  ⚠ Analytics session store not available — skipping.")


# ─── Per-user reset ───────────────────────────────────────────────────────────

def list_all_users():
    from database.session import SessionLocal
    db = SessionLocal()
    try:
        return db.query(User).order_by(User.created_at.desc()).all()
    finally:
        db.close()


def select_user_interactive() -> Optional[str]:
    users = list_all_users()
    if not users:
        print("\n⚠  No users found in database.")
        return None

    print("\n── Select a User ────────────────────────────────────")
    for i, u in enumerate(users, 1):
        print(f"  [{i}] {(u.email or '(no email)'):<35s}  Name: {u.name or '(unnamed)'}")
        print(f"      ID: {u.id}")

    print()
    try:
        choice = input(f"  Enter number [1-{len(users)}] (or 'q' to quit): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n⚠  Cancelled.")
        return None

    if choice.lower() == "q":
        return None

    try:
        idx = int(choice)
    except ValueError:
        print("✗ Invalid input.")
        return None

    if 1 <= idx <= len(users):
        selected = users[idx - 1]
        print(f"  ✓ Selected: {selected.email} ({selected.id})")
        return str(selected.id)

    print("✗ Out of range.")
    return None


def reset_user_data(user_id: str) -> None:
    """Reset all data for a specific user: Redis usage keys + PostgreSQL rows."""
    print(f"\n── Resetting data for user: {user_id} ──────────────")

    # 1. Redis — clear per-user usage/rate keys
    try:
        r = _make_redis_client()
        patterns = [
            f"usage:queries:{user_id}",
            f"usage:datasets:{user_id}",
            f"usage:analytics:*:{user_id}",
            f"ratelimit:{user_id}:*",
        ]
        deleted = 0
        for pattern in patterns:
            keys = list(r.scan_iter(match=pattern, count=500))
            if keys:
                r.delete(*keys)
                deleted += len(keys)
        print(f"  ✓ Redis: deleted {deleted} user keys")
    except Exception as exc:
        print(f"  ✗ Redis error: {exc}")

    # 2. PostgreSQL — delete user's chats, messages, datasets
    try:
        with reset_engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM messages WHERE chat_id IN "
                "(SELECT id FROM chats WHERE user_id = CAST(:user_id AS uuid))"
            ), {"user_id": user_id})
            conn.execute(text("DELETE FROM deleted_chats WHERE user_id = CAST(:user_id AS uuid)"), {"user_id": user_id})
            conn.execute(text("DELETE FROM chats WHERE user_id = CAST(:user_id AS uuid)"), {"user_id": user_id})
            conn.execute(text("DELETE FROM user_datasets WHERE user_id = CAST(:user_id AS uuid)"), {"user_id": user_id})
            conn.execute(text("DELETE FROM analytics_runs WHERE user_id = CAST(:user_id AS uuid)"), {"user_id": user_id})
        print("  ✓ PostgreSQL: deleted messages, chats, deleted_chats, datasets, analytics_runs")
    except Exception as exc:
        print(f"  ✗ PostgreSQL error: {exc}")

    print(f"\n  ✨ User {user_id} data reset complete.")


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="DataForgeAI system reset")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--user", action="store_true", help="Reset a specific user's data (interactive)")
    parser.add_argument("--redis", action="store_true", help="Reset only Redis")
    parser.add_argument("--postgres", action="store_true", help="Reset only PostgreSQL")
    args = parser.parse_args()

    # ── Selective component reset
    if args.redis or args.postgres:
        if args.redis:
            reset_redis()
        if args.postgres:
            reset_postgres()
        print("\n  ✨ Selective reset complete.")
        sys.exit(0)

    # ── Per-user reset
    if args.user:
        user_id = select_user_interactive()
        if user_id:
            confirm = input(f"\n  ⚠  Delete ALL data for this user? Type 'YES': ").strip()
            if confirm == "YES":
                reset_user_data(user_id)
            else:
                print("  Aborted.")
        sys.exit(0)

    # ── Full system reset
    print("╔══════════════════════════════════════════════════╗")
    print("║       DataForgeAI — FULL SYSTEM RESET           ║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    print("  ⚠  Targeting LIVE cloud services:")
    print(f"     PostgreSQL : {settings.DATABASE_HOST}:{settings.DATABASE_PORT} / {settings.DATABASE_NAME}")
    print(f"     Redis      : {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    print()
    print("  This will PERMANENTLY DELETE and RECREATE:")
    print("  1. All PostgreSQL tables (users, chats, messages, datasets, …)")
    print("  2. All Redis keys (rate limits, usage counters, caches)")
    print("  3. In-memory analytics sessions")

    if not args.yes:
        answer = input("\n  ⚠  Type 'DELETE' to confirm full reset (or anything else to abort): ").strip()
        if answer != "DELETE":
            print("  Aborted.")
            sys.exit(0)

    reset_postgres()
    reset_redis()
    reset_analytics_sessions()

    print("\n══════════════════════════════════════════════════════")
    print("  ✨ Full system reset complete. Restart the backend.")
    print("══════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
