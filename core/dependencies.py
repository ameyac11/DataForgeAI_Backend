import logging
from fastapi import Depends, Request, HTTPException
from sqlalchemy.orm import Session
from database.session import get_db
from auth.jwt_handler import verify_token
from database.models import User

logger = logging.getLogger("dataforge.core.dependencies")


def require_auth_cookie(request: Request) -> str:
    """Extract and verify JWT from httponly cookie. Returns user_id."""
    token = request.cookies.get("access_token")
    if not token:
        logger.warning("[AUTH] Missing access_token cookie from %s %s", request.method, request.url.path)
        raise HTTPException(status_code=401, detail="Not authenticated. Please log in.")
    payload = verify_token(token)
    if not payload:
        logger.warning("[AUTH] Invalid or expired token from %s %s", request.method, request.url.path)
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return payload.get("sub")


def get_current_user(
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
) -> User:
    """Get full user object from DB."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error("[AUTH] User '%s' from valid token not found in database", user_id)
        raise HTTPException(status_code=404, detail="User account not found. Please contact support.")
    return user
