"""Appwrite object storage for dataset files."""
import os
import logging

try:
    from appwrite.client import Client
    from appwrite.services.storage import Storage
    from appwrite.input_file import InputFile
    from appwrite.id import ID
    APPWRITE_STORAGE_AVAILABLE = True
except ImportError:
    APPWRITE_STORAGE_AVAILABLE = False

from config import get_settings

logger = logging.getLogger("dataforge.storage")
settings = get_settings()

LOCAL_STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "local_storage")


def _get_storage():
    """Get Appwrite Storage service instance."""
    if not APPWRITE_STORAGE_AVAILABLE:
        return None
    if not settings.APPWRITE_PROJECT_ID or not settings.APPWRITE_API_KEY:
        return None
    client = Client()
    client.set_endpoint(settings.APPWRITE_ENDPOINT)
    client.set_project(settings.APPWRITE_PROJECT_ID)
    client.set_key(settings.APPWRITE_API_KEY)
    return Storage(client)


def upload_file(content: bytes, file_id: str, filename: str) -> dict:
    """Upload file bytes to Appwrite storage. Falls back to local storage in dev."""
    storage = _get_storage()
    if not storage or not settings.APPWRITE_BUCKET_ID:
        # Dev fallback: store locally
        local_dir = os.path.join(LOCAL_STORAGE_DIR, "datasets")
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, file_id)
        with open(local_path, "wb") as f:
            f.write(content)
        return {"$id": file_id, "name": filename, "sizeOriginal": len(content)}

    result = storage.create_file(
        bucket_id=settings.APPWRITE_BUCKET_ID,
        file_id=file_id,
        file=InputFile.from_bytes(content, filename),
    )
    return result


def download_file(file_id: str) -> bytes:
    """Download file from Appwrite storage. Falls back to local storage in dev."""
    storage = _get_storage()
    if not storage or not settings.APPWRITE_BUCKET_ID:
        local_path = os.path.join(LOCAL_STORAGE_DIR, "datasets", file_id)
        if not os.path.exists(local_path):
            logger.error("[STORAGE] Local file not found: %s", local_path)
            raise FileNotFoundError(f"Dataset file not found in local storage: {file_id}")
        with open(local_path, "rb") as f:
            return f.read()

    return storage.get_file_download(
        bucket_id=settings.APPWRITE_BUCKET_ID,
        file_id=file_id,
    )


def delete_file(file_id: str) -> bool:
    """Delete file from Appwrite storage. Falls back to local storage in dev."""
    storage = _get_storage()
    if not storage or not settings.APPWRITE_BUCKET_ID:
        local_path = os.path.join(LOCAL_STORAGE_DIR, "datasets", file_id)
        if os.path.exists(local_path):
            os.remove(local_path)
        return True

    try:
        storage.delete_file(
            bucket_id=settings.APPWRITE_BUCKET_ID,
            file_id=file_id,
        )
        return True
    except Exception as e:
        logger.error("[STORAGE] Failed to delete file '%s' from Appwrite: %s: %s", file_id, type(e).__name__, e)
        return False
