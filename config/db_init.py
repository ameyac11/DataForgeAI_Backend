"""
MongoDB Database Initialization Module

This module handles the creation of collections, indexes, and seed data
for the model usage limiting system.
"""

import os
from datetime import datetime
from typing import Dict, Any, List
from pymongo import MongoClient, ASCENDING
from pymongo.errors import CollectionInvalid, DuplicateKeyError
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

MONGODB_URL = os.getenv("MONGODB_URL")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE")

# Collection names
USERS_COLLECTION = "users"
MODEL_LIMITS_COLLECTION = "model_limits"
USER_MODEL_USAGE_COLLECTION = "user_model_usage"
SESSIONS_COLLECTION = "sessions"


def get_init_client():
    """Get MongoDB client for initialization."""
    return MongoClient(MONGODB_URL)


def initialize_users_collection(db) -> bool:
    """
    Initialize users collection with proper schema and indexes.
    
    Schema:
    - _id (ObjectId, primary key)
    - id (string, legacy compatibility)
    - email (string, unique)
    - username (string)
    - password (string, optional for Google users)
    - authProviders.email (boolean)
    - authProviders.google.id (string, optional)
    - authProviders.google.email (string, optional)
    - google_id (string, optional - legacy)
    - picture (string, optional)
    - created_at (string/timestamp)
    - is_active (boolean)
    """
    collection = db[USERS_COLLECTION]
    
    try:
        # Create unique index on email (case-insensitive)
        collection.create_index(
            [("email", ASCENDING)],
            unique=True,
            collation={"locale": "en", "strength": 2},
            name="email_unique_idx"
        )
        
        # Create index on id field for legacy compatibility
        collection.create_index(
            [("id", ASCENDING)],
            unique=True,
            sparse=True,
            name="id_unique_idx"
        )
        
        # Create index on google_id for fast lookups
        collection.create_index(
            [("google_id", ASCENDING)],
            sparse=True,
            name="google_id_idx"
        )
        
        # Create index on authProviders.google.id
        collection.create_index(
            [("authProviders.google.id", ASCENDING)],
            sparse=True,
            name="auth_google_id_idx"
        )
        
        return True
        
    except Exception as e:
        return False


def initialize_model_limits_collection(db) -> bool:
    """
    Initialize model_limits collection.
    Model limits are managed directly in MongoDB - no seed data in code.
    
    Schema:
    - _id (string, model name - primary key)
    - daily_limit (number)
    - enabled (boolean)
    - fallback_models (array of model names)
    - display_name (string)
    - priority (number)
    """
    # Collection is created automatically when first document is inserted
    # No indexes needed - _id is already indexed by default
    return True


def initialize_user_model_usage_collection(db) -> bool:
    """
    Initialize user_model_usage collection for tracking.
    
    Schema (ONE document per user per day):
    - _id (ObjectId)
    - userId (string, reference to users.id)
    - date (string, YYYY-MM-DD)
    - models (object with model counts):
        - gpt-4.1: number
        - gpt-4o: number
        - gpt-4.1-mini: number
        - gpt-4o-mini: number
        - gpt-4.1-nano: number
    - createdAt (timestamp)
    - updatedAt (timestamp)
    
    Composite unique index on (userId, date) ensures
    one record per user per day.
    """
    collection = db[USER_MODEL_USAGE_COLLECTION]
    
    try:
        # Create composite unique index on userId + date (one doc per user per day)
        collection.create_index(
            [
                ("userId", ASCENDING),
                ("date", ASCENDING)
            ],
            unique=True,
            name="user_date_unique_idx"
        )
        
        # Create index for querying by userId
        collection.create_index(
            [("userId", ASCENDING)],
            name="userId_idx"
        )
        
        # Create index for date-based queries (cleanup/analytics)
        collection.create_index(
            [("date", ASCENDING)],
            name="date_idx"
        )
        
        return True
        
    except Exception as e:
        return False


def initialize_sessions_collection(db) -> bool:
    """
    Initialize sessions collection for session tracking.
    
    Schema:
    - _id (ObjectId)
    - userId (string, reference to users.id)
    - provider (string: 'email' | 'google')
    - token (string, hashed)
    - createdAt (timestamp)
    - expiresAt (timestamp)
    """
    collection = db[SESSIONS_COLLECTION]
    
    try:
        # Create index on userId for fast session lookups
        collection.create_index(
            [("userId", ASCENDING)],
            name="userId_idx"
        )
        
        # Create TTL index for automatic session expiration
        collection.create_index(
            [("expiresAt", ASCENDING)],
            expireAfterSeconds=0,
            name="session_expiry_ttl_idx"
        )
        
        return True
        
    except Exception as e:
        return False


def initialize_database() -> Dict[str, bool]:
    """
    Initialize all MongoDB collections and indexes.
    Returns a dict with status for each collection.
    """
    client = get_init_client()
    db = client[MONGODB_DATABASE]
    
    results = {
        USERS_COLLECTION: initialize_users_collection(db),
        MODEL_LIMITS_COLLECTION: initialize_model_limits_collection(db),
        USER_MODEL_USAGE_COLLECTION: initialize_user_model_usage_collection(db),
        SESSIONS_COLLECTION: initialize_sessions_collection(db)
    }
    
    client.close()
    return results


def verify_database_state() -> Dict[str, Any]:
    """
    Verify the current state of all collections.
    Returns information about each collection.
    """
    client = get_init_client()
    db = client[MONGODB_DATABASE]
    
    state = {}
    
    for collection_name in [USERS_COLLECTION, MODEL_LIMITS_COLLECTION, 
                            USER_MODEL_USAGE_COLLECTION, SESSIONS_COLLECTION]:
        collection = db[collection_name]
        state[collection_name] = {
            "exists": collection_name in db.list_collection_names(),
            "count": collection.count_documents({}),
            "indexes": list(collection.index_information().keys())
        }
    
    client.close()
    return state


if __name__ == "__main__":
    # Run initialization when executed directly
    results = initialize_database()
    
    print("\n📋 Database State:")
    state = verify_database_state()
    for name, info in state.items():
        print(f"  {name}:")
        print(f"    - Documents: {info['count']}")
        print(f"    - Indexes: {info['indexes']}")
