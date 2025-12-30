import os
import uuid
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv
from utils.timezone import get_ist_now, get_ist_date_str, seconds_until_midnight_ist, get_ist_iso
from services.redis_service import get_redis_service

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

MONGODB_URL = os.getenv("MONGODB_URL")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE")

MODEL_LIMITS_COLLECTION = "model_limits"
USER_MODEL_USAGE_COLLECTION = "user_model_usage"
SESSIONS_COLLECTION = "sessions"

ANONYMOUS_PREFIX = "anon_"

MODEL_CATEGORIES = {
    "selectable": ["gpt-4.1", "gpt-4o", "gpt-4.1-mini", "gpt-4o-mini"],
    "nano_internal": "gpt-4.1-nano",
    "analytics": "meta/Llama-3.3-70B-Instruct"
}

class ModelLimitsService:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._client: Optional[MongoClient] = None
        self._db = None
        self._redis = get_redis_service()
        
        self._limits_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)
        
        self._initialized = True
    
    def _get_db(self):
        if self._client is None:
            self._client = MongoClient(MONGODB_URL)
            self._db = self._client[MONGODB_DATABASE]
        return self._db
    
    def _should_refresh_cache(self) -> bool:
        if not self._cache_timestamp:
            return True
        return datetime.utcnow() - self._cache_timestamp > self._cache_ttl
    
    def _is_anonymous_id(self, user_id: str) -> bool:
        return user_id and user_id.startswith(ANONYMOUS_PREFIX)
    
    def create_anonymous_session(self) -> str:
        db = self._get_db()
        collection = db[SESSIONS_COLLECTION]
        
        session_id = f"{ANONYMOUS_PREFIX}{uuid.uuid4().hex}"
        now = get_ist_now()
        
        try:
            collection.insert_one({
                "sessionId": session_id,
                "userId": None,
                "provider": "anonymous",
                "createdAt": get_ist_iso(),
                "expiresAt": (now + timedelta(days=30)).isoformat(),
                "isAnonymous": True
            })
        except Exception:
            pass
        
        return session_id
    
    def validate_anonymous_session(self, session_id: str) -> bool:
        if not session_id or not self._is_anonymous_id(session_id):
            return False
            
        db = self._get_db()
        collection = db[SESSIONS_COLLECTION]
        
        try:
            session = collection.find_one({
                "sessionId": session_id,
                "isAnonymous": True,
                "expiresAt": {"$gt": get_ist_iso()}
            })
            return session is not None
        except Exception:
            return False
    
    def get_or_create_anonymous_session(self, session_id: Optional[str] = None) -> str:
        if session_id and self.validate_anonymous_session(session_id):
            return session_id
        return self.create_anonymous_session()
    
    def refresh_limits_cache(self) -> None:
        db = self._get_db()
        collection = db[MODEL_LIMITS_COLLECTION]
        
        try:
            limits = list(collection.find({}))
            self._limits_cache = {doc["_id"]: doc for doc in limits}
            self._cache_timestamp = datetime.utcnow()
            
            if self._redis.is_available():
                self._redis.clear_model_cache()
                for doc in limits:
                    self._redis.set_model_limit_config(
                        doc["_id"],
                        doc.get("daily_limit", 999999),
                        doc.get("enabled", True),
                        doc.get("fallback_models", [])
                    )
        except Exception:
            pass
    
    def get_model_limits(self, model_id: str) -> Optional[Dict[str, Any]]:
        if self._redis.is_available():
            cached = self._redis.get_model_limit_config(model_id)
            if cached:
                return cached
        
        if self._should_refresh_cache():
            self.refresh_limits_cache()
        
        return self._limits_cache.get(model_id)
    
    def _get_effective_limit(self, model_id: str, user_id: str) -> int:
        limits = self.get_model_limits(model_id)
        if not limits:
            return 999999
        
        base_limit = limits.get("daily_limit", 999999)
        is_anonymous = self._is_anonymous_id(user_id)
        
        if is_anonymous:
            return base_limit // 2
        
        return base_limit
    
    def _sanitize_model_key(self, model_id: str) -> str:
        return model_id.replace(".", "_").replace("/", "_")
    
    def _unsanitize_model_key(self, key: str) -> str:
        return key.replace("_", ".")
    
    def get_user_usage(self, user_id: str, model_id: str, date: str = None) -> int:
        if not user_id:
            return 0
        
        if self._redis.is_available():
            usage = self._redis.get_daily_limit(user_id, model_id)
            if usage is not None:
                return usage
        
        db = self._get_db()
        collection = db[USER_MODEL_USAGE_COLLECTION]
        date = date or get_ist_date_str()
        model_key = self._sanitize_model_key(model_id)
        
        try:
            doc = collection.find_one({
                "userId": user_id,
                "date": date
            })
            if doc and "models" in doc:
                return doc["models"].get(model_key, 0)
            return 0
        except Exception:
            return 0
    
    def increment_usage(self, user_id: str, model_id: str) -> int:
        if not user_id:
            return 0
        
        new_count = 1
        
        if self._redis.is_available():
            redis_count = self._redis.increment_daily_limit(user_id, model_id)
            if redis_count is not None:
                new_count = redis_count
        
        db = self._get_db()
        collection = db[USER_MODEL_USAGE_COLLECTION]
        date = get_ist_date_str()
        now_iso = get_ist_iso()
        model_key = self._sanitize_model_key(model_id)
        
        try:
            result = collection.find_one_and_update(
                {
                    "userId": user_id,
                    "date": date
                },
                {
                    "$inc": {f"models.{model_key}": 1},
                    "$set": {"updatedAt": now_iso},
                    "$setOnInsert": {"createdAt": now_iso}
                },
                upsert=True,
                return_document=ReturnDocument.AFTER
            )
            return result["models"].get(model_key, 1) if result else 1
        except Exception:
            return new_count
    
    def check_model_available(self, user_id: str, model_id: str) -> Tuple[bool, str]:
        limits = self.get_model_limits(model_id)
        
        if not limits:
            return True, ""
        
        if not limits.get("enabled", True):
            return False, "temporarily_unavailable"
        
        if not user_id:
            return True, ""
        
        current_usage = self.get_user_usage(user_id, model_id)
        daily_limit = self._get_effective_limit(model_id, user_id)
        
        if current_usage >= daily_limit:
            return False, "limit_reached"
        
        return True, ""
    
    def get_available_model(
        self, 
        user_id: str, 
        requested_model: str,
        fallback_chain: List[str] = None
    ) -> Tuple[str, Optional[str]]:
        if not user_id:
            limits = self.get_model_limits(requested_model)
            if limits and not limits.get("enabled", True):
                fallbacks = limits.get("fallback_models", [])
                for fb in fallbacks:
                    fb_limits = self.get_model_limits(fb)
                    if fb_limits and fb_limits.get("enabled", True):
                        return fb, None
                return "gpt-4.1-nano", None
            return requested_model, None
        
        is_available, reason = self.check_model_available(user_id, requested_model)
        
        if is_available:
            return requested_model, None
        
        limits = self.get_model_limits(requested_model)
        fallbacks = fallback_chain or (limits.get("fallback_models", []) if limits else [])
        
        for fallback_model in fallbacks:
            fb_available, fb_reason = self.check_model_available(user_id, fallback_model)
            if fb_available:
                message = self._get_fallback_message(requested_model, fallback_model, reason)
                return fallback_model, message
        
        nano_available, _ = self.check_model_available(user_id, "gpt-4.1-nano")
        if nano_available:
            return "gpt-4.1-nano", self._get_fallback_message(
                requested_model, "gpt-4.1-nano", reason
            )
        
        return None, "all_models_unavailable"
    
    def _get_fallback_message(
        self, 
        original_model: str, 
        fallback_model: str, 
        reason: str
    ) -> Optional[str]:
        high_tier = {"gpt-4.1", "gpt-4o"}
        mid_tier = {"gpt-4.1-mini", "gpt-4o-mini"}
        
        if reason == "temporarily_unavailable":
            if original_model in high_tier:
                return "advanced_reasoning_unavailable"
            return "model_temporarily_unavailable"
        
        if reason == "limit_reached":
            if original_model in high_tier and fallback_model in mid_tier:
                return "switched_to_balanced_model"
            elif fallback_model == "gpt-4.1-nano":
                return "switched_to_fast_model"
            return "using_alternative_model"
        
        return None
    
    def record_usage(self, user_id: str, model_id: str) -> None:
        if user_id:
            self.increment_usage(user_id, model_id)
    
    def get_user_daily_summary(self, user_id: str) -> Dict[str, int]:
        if not user_id:
            return {}
            
        db = self._get_db()
        collection = db[USER_MODEL_USAGE_COLLECTION]
        date = get_ist_date_str()
        
        try:
            doc = collection.find_one({
                "userId": user_id,
                "date": date
            })
            if doc and "models" in doc:
                return {self._unsanitize_model_key(k): v for k, v in doc["models"].items()}
            return {}
        except Exception:
            return {}

_model_limits_service: Optional[ModelLimitsService] = None

def get_model_limits_service() -> ModelLimitsService:
    global _model_limits_service
    if _model_limits_service is None:
        _model_limits_service = ModelLimitsService()
    return _model_limits_service

def check_and_get_model(
    user_id: Optional[str], 
    requested_model: str
) -> Tuple[Optional[str], Optional[str]]:
    service = get_model_limits_service()
    return service.get_available_model(user_id, requested_model)

def record_model_usage(user_id: Optional[str], model_id: str) -> None:
    if user_id:
        service = get_model_limits_service()
        service.record_usage(user_id, model_id)

def get_status_message_text(status_code: Optional[str]) -> Optional[str]:
    messages = {
        "advanced_reasoning_unavailable": "Advanced reasoning is temporarily unavailable.",
        "model_temporarily_unavailable": "This model is temporarily unavailable.",
        "switched_to_balanced_model": "Switched to a balanced model to continue processing.",
        "switched_to_fast_model": "Switched to a fast model so you can continue.",
        "using_alternative_model": "Using an alternative model to process your request.",
        "all_models_unavailable": "Our AI models are currently at capacity. Please try again shortly."
    }
    return messages.get(status_code) if status_code else None
