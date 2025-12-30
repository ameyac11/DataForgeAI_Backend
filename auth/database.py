import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from passlib.context import CryptContext
from jose import JWTError, jwt
from .models import UserCreate, UserResponse
import uuid
from config.mongodb import get_sync_database, USERS_COLLECTION
from utils.timezone import get_ist_iso

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Get MongoDB database
def get_users_collection():
    """Get the users collection from MongoDB"""
    db = get_sync_database()
    return db[USERS_COLLECTION]

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Generate password hash"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> Optional[str]:
    """Verify JWT token and return user_id"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        return user_id
    except JWTError:
        return None

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get user by email from MongoDB"""
    collection = get_users_collection()
    user = collection.find_one({"email": {"$regex": f"^{email}$", "$options": "i"}})
    if user:
        user["id"] = user.get("id", str(user.get("_id")))
        return user
    return None

def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user by ID from MongoDB"""
    collection = get_users_collection()
    user = collection.find_one({"id": user_id})
    if user:
        return user
    return None

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Get user by username from MongoDB"""
    collection = get_users_collection()
    user = collection.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
    if user:
        user["id"] = user.get("id", str(user.get("_id")))
        return user
    return None

def create_user(user_data: UserCreate) -> UserResponse:
    """Create a new user in MongoDB"""
    collection = get_users_collection()
    
    # Check if email already exists
    if get_user_by_email(user_data.email):
        raise ValueError("Email already registered")
    
    # Check if username already exists
    if get_user_by_username(user_data.username):
        raise ValueError("Username already taken")
    
    user_id = str(uuid.uuid4())
    hashed_password = get_password_hash(user_data.password)
    
    new_user = {
        "id": user_id,
        "email": user_data.email,
        "username": user_data.username,
        "password": hashed_password,
        "created_at": get_ist_iso(),
        "is_active": True,
        "auth_provider": "email",
        "authProviders": {
            "email": True,
            "google": None
        }
    }
    
    collection.insert_one(new_user)
    
    return UserResponse(**new_user)

def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate user with email and password"""
    user = get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password"]):
        return None
    return user

def update_user(user_id: str, update_data: Dict[str, Any]) -> Optional[UserResponse]:
    """Update user in MongoDB"""
    collection = get_users_collection()
    
    # Don't allow updating the id
    if "id" in update_data:
        del update_data["id"]
    
    result = collection.find_one_and_update(
        {"id": user_id},
        {"$set": update_data},
        return_document=True
    )
    
    if result:
        return UserResponse(**result)
    return None

# Unified OAuth functions
def get_or_create_user_with_provider(email: str, provider: str, provider_id: str, provider_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Unified function to get or create a user with OAuth provider.
    Creates one user document that can support multiple auth providers.
    """
    collection = get_users_collection()

    # Check if user exists with this provider
    user = collection.find_one({
        f"authProviders.{provider}.id": provider_id
    })

    if user:
        # User exists with this provider, return it
        return user

    # Check if user exists with this email
    user = collection.find_one({"email": {"$regex": f"^{email}$", "$options": "i"}})

    if user:
        # User exists with email, add this provider to their account
        update_data = {
            f"authProviders.{provider}": {
                "id": provider_id,
                "email": email,
                **(provider_data or {})
            }
        }

        collection.update_one(
            {"id": user["id"]},
            {"$set": update_data}
        )

        # Update the user object and return
        user[f"authProviders"][provider] = update_data[f"authProviders.{provider}"]
        return user

    # Create new user
    user_id = str(uuid.uuid4())

    # Generate username based on provider data
    if provider == "google":
        username = provider_data.get("name") or email.split("@")[0]
    elif provider == "github":
        username = provider_data.get("login") or email.split("@")[0] if email else f"user_{user_id[:8]}"
    else:
        username = email.split("@")[0]

    # Ensure username is unique
    base_username = username
    counter = 1
    while get_user_by_username(username):
        username = f"{base_username}{counter}"
        counter += 1

    # Create unified user document
    new_user = {
        "id": user_id,
        "email": email,
        "username": username,
        "created_at": get_ist_iso(),
        "is_active": True,
        "auth_provider": provider,  # Primary provider (last used)
        "authProviders": {
            "email": False,  # No password set initially
            "google": None,
            "github": None
        }
    }

    # Set provider-specific data
    new_user["authProviders"][provider] = {
        "id": provider_id,
        "email": email,
        **(provider_data or {})
    }

    # Add provider-specific fields for backward compatibility
    if provider == "google":
        new_user["google_id"] = provider_id
        new_user["picture"] = provider_data.get("picture")
    elif provider == "github":
        new_user["github_id"] = provider_id
        new_user["avatar_url"] = provider_data.get("avatar_url")

    collection.insert_one(new_user)

    return new_user

# Google OAuth related functions
def get_or_create_google_user(google_user_info: Dict[str, Any]) -> Dict[str, Any]:
    """Get or create user with Google OAuth"""
    email = google_user_info.get("email")
    google_id = google_user_info.get("sub") or google_user_info.get("id")

    provider_data = {
        "name": google_user_info.get("name"),
        "picture": google_user_info.get("picture"),
        "verified_email": google_user_info.get("email_verified", False)
    }

    return get_or_create_user_with_provider(email, "google", google_id, provider_data)

# GitHub OAuth related functions
def get_or_create_github_user(github_user_info: Dict[str, Any]) -> Dict[str, Any]:
    """Get or create user with GitHub OAuth"""
    email = github_user_info.get("email")
    github_id = str(github_user_info.get("id"))

    provider_data = {
        "login": github_user_info.get("login"),
        "avatar_url": github_user_info.get("avatar_url"),
        "name": github_user_info.get("name"),
        "company": github_user_info.get("company"),
        "location": github_user_info.get("location"),
        "bio": github_user_info.get("bio")
    }

    return get_or_create_user_with_provider(email, "github", github_id, provider_data)
