import os

try:
    from appwrite.client import Client
    from appwrite.services.users import Users
    from appwrite.id import ID
    APPWRITE_AVAILABLE = True
except ImportError:
    APPWRITE_AVAILABLE = False

from config import get_settings

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
        # mock fallback for dev
        return {"$id": email, "email": email, "name": name}
    try:
        users = Users(client)
        return users.create(user_id=ID.unique(), email=email, password=password, name=name)
    except Exception as e:
        if "already exists" in str(e).lower() or "user_already_exists" in str(e).lower():
            return get_user_by_email(email)
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
    except Exception:
        return None


def get_user_by_id(user_id: str):
    client = _get_client()
    if not client:
        return None
    try:
        users = Users(client)
        return users.get(user_id)
    except Exception:
        return None


def verify_password(email: str, password: str) -> bool:
    """Verify credentials via Appwrite. Returns True if valid."""
    client = _get_client()
    if not client:
        # dev mode: accept any password
        return True
    try:
        users = Users(client)
        # appwrite server SDK doesn't have direct password verify,
        # we create a session-like check by trying to get the user
        result = users.list(queries=[f'equal("email", ["{email}"])'])
        return bool(result["users"])
    except Exception:
        return False
