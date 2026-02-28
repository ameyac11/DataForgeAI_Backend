import uuid
import time
import logging
import threading
from typing import Optional

logger = logging.getLogger("dataforge.analytics.session")

# in-memory session store
_sessions: dict[str, dict] = {}
_lock = threading.Lock()

SESSION_TTL = 1800  # 30 min timeout


def create_session(df, filename: str, file_size: int) -> str:
    session_id = uuid.uuid4().hex[:16]
    with _lock:
        _sessions[session_id] = {
            "df": df,
            "filename": filename,
            "file_size": file_size,
            "created_at": time.time(),
            "last_access": time.time(),
        }
    logger.info("Session %s created for %s (%d bytes)", session_id, filename, file_size)
    return session_id


def get_session(session_id: str) -> Optional[dict]:
    with _lock:
        session = _sessions.get(session_id)
        if session:
            session["last_access"] = time.time()
        return session


def delete_session(session_id: str):
    with _lock:
        removed = _sessions.pop(session_id, None)
    if removed:
        logger.info("Session %s deleted", session_id)


def cleanup_expired():
    now = time.time()
    with _lock:
        expired = [sid for sid, s in _sessions.items() if now - s["last_access"] > SESSION_TTL]
        for sid in expired:
            del _sessions[sid]
    if expired:
        logger.info("Cleaned up %d expired sessions", len(expired))


def get_active_count() -> int:
    with _lock:
        return len(_sessions)
