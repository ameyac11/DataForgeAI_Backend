import uuid
import json
import base64
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from database.session import get_db
from database.models import UserDataset
from core.dependencies import require_auth_cookie
from core.responses import success_response, error_response
from storage.appwrite_storage import upload_file, download_file, delete_file

logger = logging.getLogger("dataforge.api.datasets")

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])

MAX_DATASETS = 10
MAX_FILE_SIZE = 2_097_152  # 2MB in bytes


@router.get("")
def list_datasets(user_id: str = Depends(require_auth_cookie), db: Session = Depends(get_db)):
    # list user datasets
    datasets = db.query(UserDataset).filter(
        UserDataset.user_id == user_id
    ).order_by(UserDataset.created_at.desc()).all()

    return success_response({
        "datasets": [
            {
                "id": str(d.id),
                "dataset_name": d.dataset_name,
                "generation_mode": d.generation_mode,
                "model_used": d.model_used,
                "file_size_bytes": d.file_size_bytes,
                "file_path": d.file_path,
                "created_at": d.created_at.isoformat(),
            }
            for d in datasets
        ],
        "count": len(datasets),
        "limit": MAX_DATASETS,
    })


@router.get("/{dataset_id}/download")
def download_dataset(
    dataset_id: str,
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    # download dataset file
    dataset = db.query(UserDataset).filter(
        UserDataset.id == dataset_id,
        UserDataset.user_id == user_id,
    ).first()

    if not dataset:
        logger.warning("[DATASET DOWNLOAD] Dataset '%s' not found for user '%s'", dataset_id, user_id)
        return error_response("Dataset not found", 404)

    try:
        content = download_file(str(dataset.id))

        # set content type
        ext = dataset.file_path.split(".")[-1].lower() if "." in dataset.file_path else "json"
        content_types = {
            "json": "application/json",
            "csv": "text/csv",
            "sql": "application/sql",
            "parquet": "application/octet-stream",
        }
        content_type = content_types.get(ext, "application/octet-stream")
        filename = f"{dataset.dataset_name}.{ext}"

        return Response(
            content=content,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except FileNotFoundError:
        logger.error("[DATASET DOWNLOAD] File not found in storage for dataset '%s'", dataset_id)
        return error_response("Dataset file not found in storage. It may have been deleted.", 404)
    except Exception as e:
        logger.error("[DATASET DOWNLOAD] Failed for dataset '%s': %s: %s", dataset_id, type(e).__name__, e)
        return error_response(f"Failed to download dataset. Please try again.", 500)


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: str,
    user_id: str = Depends(require_auth_cookie),
    db: Session = Depends(get_db),
):
    # delete dataset completely
    dataset = db.query(UserDataset).filter(
        UserDataset.id == dataset_id,
        UserDataset.user_id == user_id,
    ).first()

    if not dataset:
        logger.warning("[DATASET DELETE] Dataset '%s' not found for user '%s'", dataset_id, user_id)
        return error_response("Dataset not found", 404)

    # delete from storage
    try:
        delete_file(str(dataset.id))
    except Exception as e:
        logger.error("[DATASET DELETE] Failed to delete file from storage for dataset '%s': %s: %s",
                     dataset_id, type(e).__name__, e)

    # delete from db
    try:
        db.delete(dataset)
        db.commit()
    except Exception as e:
        logger.error("[DATASET DELETE] Database delete failed for dataset '%s': %s: %s",
                     dataset_id, type(e).__name__, e)
        db.rollback()
        return error_response("Failed to delete dataset from database. Please try again.", 500)

    logger.info("[DATASET DELETE] Dataset '%s' deleted by user '%s'", dataset_id, user_id)
    return success_response({"message": "Dataset deleted"})


def auto_save_dataset(
    user_id: str,
    data,
    fmt: str,
    dataset_name: str,
    model_id: str,
    data_mode: str,
    db: Session,
) -> dict:
    # auto save generated dataset

    # serialize data
    if fmt == "json":
        if isinstance(data, list):
            content = json.dumps(data, indent=2).encode("utf-8")
        elif isinstance(data, str):
            content = data.encode("utf-8")
        else:
            content = json.dumps(data, indent=2).encode("utf-8")
    elif fmt in ("csv", "sql"):
        content = data.encode("utf-8") if isinstance(data, str) else str(data).encode("utf-8")
    elif fmt == "parquet":
        content = base64.b64decode(data) if isinstance(data, str) else data
    else:
        content = json.dumps(data).encode("utf-8") if not isinstance(data, str) else data.encode("utf-8")

    file_size = len(content)

    # check file size
    if file_size > MAX_FILE_SIZE:
        return {
            "save_status": "size_exceeded",
            "save_message": "Dataset exceeds 2MB limit. Please reduce dataset size.",
            "dataset_id": None,
        }

    # check user limits
    count = db.query(func.count(UserDataset.id)).filter(
        UserDataset.user_id == user_id
    ).scalar() or 0

    if count >= MAX_DATASETS:
        return {
            "save_status": "limit_exceeded",
            "save_message": f"Your dataset storage is full ({count}/{MAX_DATASETS}). Please delete an old dataset to save new ones.",
            "dataset_id": None,
        }

    # upload to storage
    dataset_id = str(uuid.uuid4())
    ext = fmt if fmt != "parquet" else "parquet"
    file_path = f"datasets/{user_id}/{dataset_id}.{ext}"

    try:
        upload_file(content, dataset_id, f"dataset.{ext}")
    except Exception as e:
        logger.error("[DATASET SAVE] Upload failed for user '%s': %s: %s", user_id, type(e).__name__, e)
        return {
            "save_status": "upload_failed",
            "save_message": f"Failed to save dataset to storage. Please try again.",
            "dataset_id": None,
        }

    # insert into db
    dataset = UserDataset(
        id=uuid.UUID(dataset_id),
        user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
        dataset_name=(dataset_name[:255] if dataset_name else f"Dataset {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
        generation_mode=data_mode or "synthetic",
        model_used=model_id or "unknown",
        file_size_bytes=file_size,
        file_path=file_path,
    )
    db.add(dataset)
    db.commit()

    return {
        "save_status": "saved",
        "save_message": "Dataset saved to My Datasets.",
        "dataset_id": dataset_id,
    }
