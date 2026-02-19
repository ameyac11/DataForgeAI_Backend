from fastapi import Depends, Request, HTTPException
from sqlalchemy.orm import Session
from database.session import get_db
from auth.jwt_handler import verify_token
from database.models import User


def require_auth_cookie(request: Request) -> str:
    """Extract and verify JWT from httponly cookie. Returns user_id."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload.get("sub")


def get_current_user(
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
) -> User:
    """Get full user object from DB."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
