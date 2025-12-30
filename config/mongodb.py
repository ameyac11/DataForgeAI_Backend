import os
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from typing import Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE")

MONGODB_URL = os.getenv("MONGODB_URL")

DATABASE_NAME = MONGODB_DATABASE

_async_client: Optional[AsyncIOMotorClient] = None
_sync_client: Optional[MongoClient] = None
_database = None

async def get_database():
    global _async_client, _database
    if _async_client is None:
        _async_client = AsyncIOMotorClient(MONGODB_URL)
        _database = _async_client[DATABASE_NAME]
    return _database

def get_sync_database():
    global _sync_client
    if _sync_client is None:
        _sync_client = MongoClient(MONGODB_URL)
    return _sync_client[DATABASE_NAME]

async def close_database():
    global _async_client, _sync_client
    if _async_client:
        _async_client.close()
        _async_client = None
    if _sync_client:
        _sync_client.close()
        _sync_client = None

# Collection names
USERS_COLLECTION = "users"
MODEL_LIMITS_COLLECTION = "model_limits"
USER_MODEL_USAGE_COLLECTION = "user_model_usage"
SESSIONS_COLLECTION = "sessions"