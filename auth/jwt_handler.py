from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from fastapi import Response
from config import get_settings

settings = get_settings()

ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
REFRESH_TOKEN_EXPIRE = timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + ACCESS_TOKEN_EXPIRE
    return jwt.encode({"sub": str(user_id), "exp": expire, "type": "access"}, settings.JWT_SECRET, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + REFRESH_TOKEN_EXPIRE
    return jwt.encode({"sub": str(user_id), "exp": expire, "type": "refresh"}, settings.JWT_SECRET, algorithm=ALGORITHM)


def verify_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def set_auth_cookies(response: Response, user_id: str):
    # set http cookies
    access = create_access_token(user_id)
    refresh = create_refresh_token(user_id)

    cookie_kwargs = {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.is_production,
        "domain": settings.COOKIE_DOMAIN if settings.is_production else None,
    }

    response.set_cookie("access_token", access, max_age=int(ACCESS_TOKEN_EXPIRE.total_seconds()), **cookie_kwargs)
    response.set_cookie("refresh_token", refresh, max_age=int(REFRESH_TOKEN_EXPIRE.total_seconds()), **cookie_kwargs)


def clear_auth_cookies(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
