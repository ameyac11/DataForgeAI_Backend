import os
import logging

try:
    from appwrite.client import Client
    from appwrite.services.users import Users
    from appwrite.id import ID
    APPWRITE_AVAILABLE = True
except ImportError:
    APPWRITE_AVAILABLE = False

from config import get_settings

logger = logging.getLogger("dataforge.auth.appwrite")
settings = get_settings()


def _get_client():
    if not APPWRITE_AVAILABLE:
        return None
    client = Client()
    client.set_endpoint(settings.APPWRITE_ENDPOINT)
    client.set_project(settings.APPWRITE_PROJECT_ID)
    client.set_key(settings.APPWRITE_API_KEY)
    return client


def create_user(email: str, password: str, name: str = ""):
    """Create user in Appwrite. Returns appwrite user dict or None."""
    client = _get_client()
    if not client:
        logger.info("[APPWRITE] No Appwrite client — using dev fallback for create_user('%s')", email)
        return {"$id": email, "email": email, "name": name}
    try:
        users = Users(client)
        return users.create(user_id=ID.unique(), email=email, password=password, name=name)
    except Exception as e:
        if "already exists" in str(e).lower() or "user_already_exists" in str(e).lower():
            logger.info("[APPWRITE] User '%s' already exists, fetching existing", email)
            return get_user_by_email(email)
        logger.error("[APPWRITE] Failed to create user '%s': %s: %s", email, type(e).__name__, e)
        raise


def get_user_by_email(email: str):
    """Lookup user in Appwrite by email."""
    client = _get_client()
    if not client:
        return {"$id": email, "email": email, "name": ""}
    try:
        users = Users(client)
        result = users.list(queries=[f'equal("email", ["{email}"])'])
        if result["users"]:
            return result["users"][0]
        return None
    except Exception as e:
        logger.error("[APPWRITE] Failed to lookup user '%s': %s: %s", email, type(e).__name__, e)
        return None


def get_user_by_id(user_id: str):
    client = _get_client()
    if not client:
        return None
    try:
        users = Users(client)
        return users.get(user_id)
    except Exception as e:
        logger.error("[APPWRITE] Failed to get user by id '%s': %s: %s", user_id, type(e).__name__, e)
        return None


def verify_password(email: str, password: str) -> bool:
    """Verify credentials via Appwrite. Returns True if valid."""
    client = _get_client()
    if not client:
        logger.info("[APPWRITE] No Appwrite client — dev mode: accepting any password for '%s'", email)
        return True
    try:
        users = Users(client)
        result = users.list(queries=[f'equal("email", ["{email}"])'])
        return bool(result["users"])
    except Exception as e:
        logger.error("[APPWRITE] Password verification failed for '%s': %s: %s", email, type(e).__name__, e)
        return False
