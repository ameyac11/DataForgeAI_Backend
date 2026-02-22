import uuid
import logging
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from database.session import get_db
from database.enums import AuthProvider
from auth.jwt_handler import set_auth_cookies, clear_auth_cookies, verify_token, create_access_token
from auth.appwrite_client import create_user as appwrite_create_user, verify_password
from auth.user_service import get_or_create_user_by_email, get_user_by_email, get_user_providers
from auth.oauth import get_google_auth_url, exchange_google_code, get_github_auth_url, exchange_github_code
from core.dependencies import require_auth_cookie, get_current_user
from core.responses import success_response, error_response
from config import get_settings
from database.models import User

logger = logging.getLogger("dataforge.api.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings = get_settings()


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    password: str
    username: str = ""


class OnboardingRequest(BaseModel):
    name: str
    role: Optional[str] = None
    purpose: Optional[str] = None


@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    email = req.email.lower().strip()
    if not verify_password(email, req.password):
        logger.warning("[AUTH LOGIN] Invalid credentials for email '%s'", email)
        return error_response("Invalid credentials", 401)

    user = get_user_by_email(db, email)
    if not user:
        logger.warning("[AUTH LOGIN] User not found for email '%s'", email)
        return error_response("User not found", 404)

    set_auth_cookies(response, str(user.id))
    logger.info("[AUTH LOGIN] User '%s' logged in successfully", user.id)
    return success_response({
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "onboarding_completed": user.onboarding_completed,
    })


@router.post("/signup")
def signup(req: SignupRequest, response: Response, db: Session = Depends(get_db)):
    email = req.email.lower().strip()

    # create in appwrite
    try:
        aw_user = appwrite_create_user(email, req.password, req.username)
    except Exception as exc:
        logger.error("[AUTH SIGNUP] Appwrite create_user failed for '%s': %s: %s", email, type(exc).__name__, exc)
        return error_response("Failed to create account. Please try again.", 500)

    if not aw_user:
        logger.error("[AUTH SIGNUP] Appwrite returned None for '%s'", email)
        return error_response("Failed to create account", 500)

    provider_user_id = aw_user.get("$id", email)
    user, is_new = get_or_create_user_by_email(db, email, AuthProvider.email, provider_user_id)

    if is_new and req.username:
        user.name = req.username
        db.commit()

    set_auth_cookies(response, str(user.id))
    logger.info("[AUTH SIGNUP] User '%s' signed up (is_new=%s)", user.id, is_new)
    return success_response({
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "is_new": is_new,
    })


@router.post("/logout")
def logout(response: Response):
    clear_auth_cookies(response)
    return success_response({"message": "Logged out"})


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("refresh_token")
    if not token:
        logger.warning("[AUTH REFRESH] No refresh token in cookies")
        return error_response("No refresh token", 401)

    payload = verify_token(token)
    if not payload or payload.get("type") != "refresh":
        logger.warning("[AUTH REFRESH] Invalid or expired refresh token")
        return error_response("Invalid refresh token", 401)

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning("[AUTH REFRESH] User '%s' not found during token refresh", user_id)
        return error_response("User not found", 404)

    set_auth_cookies(response, str(user.id))
    logger.info("[AUTH REFRESH] Tokens refreshed for user '%s'", user_id)
    return success_response({"message": "Tokens refreshed"})


@router.get("/me")
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    providers = get_user_providers(db, user.id)
    return success_response({
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "purpose": user.purpose,
        "onboarding_completed": user.onboarding_completed,
        "providers": providers,
    })


# --- google oauth ---

@router.get("/google")
def google_login():
    return RedirectResponse(get_google_auth_url())


@router.get("/google/callback")
async def google_callback(code: str, response: Response, db: Session = Depends(get_db)):
    try:
        user_info = await exchange_google_code(code)
        email = user_info.get("email")
        if not email:
            logger.warning("[AUTH GOOGLE] No email returned from Google OAuth")
            return RedirectResponse(f"{settings.FRONTEND_URL}/auth?error=no_email")

        provider_id = user_info.get("id", email)
        user, is_new = get_or_create_user_by_email(db, email, AuthProvider.google, str(provider_id))

        if is_new and user_info.get("name"):
            user.name = user_info["name"]
            db.commit()

        redirect = RedirectResponse(
            f"{settings.FRONTEND_URL}/onboarding" if is_new else f"{settings.FRONTEND_URL}/app"
        )
        set_auth_cookies(redirect, str(user.id))
        logger.info("[AUTH GOOGLE] User '%s' authenticated via Google (is_new=%s)", user.id, is_new)
        return redirect
    except Exception as e:
        logger.error("[AUTH GOOGLE] Google OAuth callback failed: %s: %s", type(e).__name__, e)
        return RedirectResponse(f"{settings.FRONTEND_URL}/auth?error=google_auth_failed")


# --- github oauth ---

@router.get("/github")
def github_login():
    return RedirectResponse(get_github_auth_url())


@router.get("/github/callback")
async def github_callback(code: str, response: Response, db: Session = Depends(get_db)):
    try:
        user_info = await exchange_github_code(code)
        email = user_info.get("email")
        if not email:
            logger.warning("[AUTH GITHUB] No email returned from GitHub OAuth")
            return RedirectResponse(f"{settings.FRONTEND_URL}/auth?error=no_email")

        provider_id = str(user_info.get("id", email))
        user, is_new = get_or_create_user_by_email(db, email, AuthProvider.github, provider_id)

        if is_new:
            user.name = user_info.get("name") or user_info.get("login", "")
            db.commit()

        redirect = RedirectResponse(
            f"{settings.FRONTEND_URL}/onboarding" if is_new else f"{settings.FRONTEND_URL}/app"
        )
        set_auth_cookies(redirect, str(user.id))
        logger.info("[AUTH GITHUB] User '%s' authenticated via GitHub (is_new=%s)", user.id, is_new)
        return redirect
    except Exception as e:
        logger.error("[AUTH GITHUB] GitHub OAuth callback failed: %s: %s", type(e).__name__, e)
        return RedirectResponse(f"{settings.FRONTEND_URL}/auth?error=github_auth_failed")


# --- onboarding ---

@router.post("/onboarding/complete")
def complete_onboarding(req: OnboardingRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.name = req.name
    user.role = req.role
    user.purpose = req.purpose
    user.onboarding_completed = True
    db.commit()
    return success_response({"message": "Onboarding complete"})


@router.get("/onboarding/status")
def onboarding_status(user: User = Depends(get_current_user)):
    return success_response({"completed": user.onboarding_completed})
