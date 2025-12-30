from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, Optional
from datetime import datetime

class MongoBaseModel(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True
    )

class UserDocument(MongoBaseModel):
    user_id: str = Field(...)
    email: str = Field(...)
    username: str = Field(...)
    password: str = Field(...)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)

def user_doc_to_dict(doc: UserDocument) -> Dict[str, Any]:
    return {
        "id": doc.user_id,
        "email": doc.email,
        "username": doc.username,
        "password": doc.password,
        "created_at": doc.created_at.isoformat(),
        "is_active": doc.is_active
    }

def dict_to_user_doc(data: Dict[str, Any]) -> UserDocument:
    return UserDocument(
        user_id=data["id"],
        email=data["email"],
        username=data["username"],
        password=data["password"],
        created_at=datetime.fromisoformat(data["created_at"]) if isinstance(data["created_at"], str) else data["created_at"],
        is_active=data.get("is_active", True)
    )