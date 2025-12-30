import os
import redis
import threading
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv
import pytz

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
IST = pytz.timezone('Asia/Kolkata')

class RedisService:
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
        
        self._client = None
        self._available = False
        
        if not REDIS_URL or REDIS_URL == "":
            self._initialized = True
            return
            
        try:
            self._client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=False,
                health_check_interval=30
            )
            self._client.ping()
            self._available = True
        except Exception:
            self._client = None
            self._available = False
            
        self._initialized = True
    
    def is_available(self) -> bool:
        return self._available and self._client is not None
    
    def get_ist_now(self) -> datetime:
        return datetime.now(IST)
    
    def get_ist_date_str(self) -> str:
        return self.get_ist_now().strftime("%Y-%m-%d")
    
    def get_midnight_ist(self) -> datetime:
        now = self.get_ist_now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        next_midnight = midnight + timedelta(days=1)
        return next_midnight
    
    def seconds_until_midnight_ist(self) -> int:
        now = self.get_ist_now()
        next_midnight = self.get_midnight_ist()
        delta = next_midnight - now
        return int(delta.total_seconds())
    
    def get_daily_limit(self, user_id: str, model_id: str) -> Optional[int]:
        if not self.is_available():
            return None
        
        try:
            key = f"usage:{user_id}:{model_id}:{self.get_ist_date_str()}"
            value = self._client.get(key)
            return int(value) if value else 0
        except Exception:
            return None
    
    def increment_daily_limit(self, user_id: str, model_id: str) -> Optional[int]:
        if not self.is_available():
            return None
        
        try:
            key = f"usage:{user_id}:{model_id}:{self.get_ist_date_str()}"
            ttl = self.seconds_until_midnight_ist()
            
            pipeline = self._client.pipeline()
            pipeline.incr(key)
            pipeline.expire(key, ttl)
            results = pipeline.execute()
            
            return int(results[0]) if results else None
        except Exception:
            return None
    
    def get_model_limit_config(self, model_id: str) -> Optional[dict]:
        if not self.is_available():
            return None
        
        try:
            key = f"model_config:{model_id}"
            data = self._client.hgetall(key)
            if data:
                return {
                    'daily_limit': int(data.get('daily_limit', 999999)),
                    'enabled': data.get('enabled', 'true').lower() == 'true',
                    'fallback_models': data.get('fallback_models', '').split(',') if data.get('fallback_models') else []
                }
            return None
        except Exception:
            return None
    
    def set_model_limit_config(self, model_id: str, daily_limit: int, enabled: bool, fallback_models: list) -> bool:
        if not self.is_available():
            return False
        
        try:
            key = f"model_config:{model_id}"
            self._client.hset(key, mapping={
                'daily_limit': daily_limit,
                'enabled': 'true' if enabled else 'false',
                'fallback_models': ','.join(fallback_models)
            })
            self._client.expire(key, 300)
            return True
        except Exception:
            return False
    
    def clear_model_cache(self) -> bool:
        if not self.is_available():
            return False
        
        try:
            keys = self._client.keys("model_config:*")
            if keys:
                self._client.delete(*keys)
            return True
        except Exception:
            return False
    
    def get_per_minute_limit(self, user_id: str, model_id: str) -> Optional[int]:
        if not self.is_available():
            return None
        
        try:
            key = f"rpm:{user_id}:{model_id}:{self.get_ist_now().strftime('%Y-%m-%d:%H:%M')}"
            value = self._client.get(key)
            return int(value) if value else 0
        except Exception:
            return None
    
    def increment_per_minute_limit(self, user_id: str, model_id: str) -> Optional[int]:
        if not self.is_available():
            return None
        
        try:
            key = f"rpm:{user_id}:{model_id}:{self.get_ist_now().strftime('%Y-%m-%d:%H:%M')}"
            
            pipeline = self._client.pipeline()
            pipeline.incr(key)
            pipeline.expire(key, 60)
            results = pipeline.execute()
            
            return int(results[0]) if results else None
        except Exception:
            return None
    
    def close(self):
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

_redis_service: Optional[RedisService] = None

def get_redis_service() -> RedisService:
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service

