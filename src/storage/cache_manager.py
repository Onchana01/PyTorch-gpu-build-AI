from typing import Optional, Dict, Any, TypeVar, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod
import json
import hashlib
import asyncio
from datetime import datetime, timezone, timedelta
from functools import wraps

from src.common.config.logging_config import get_logger


logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class CacheConfig:
    default_ttl_seconds: int = 3600
    max_entries: int = 10000
    redis_url: Optional[str] = None
    key_prefix: str = "cicd:"


class CacheBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError("Subclasses must implement get method")
    
    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        raise NotImplementedError("Subclasses must implement set method")
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        raise NotImplementedError("Subclasses must implement delete method")
    
    @abstractmethod
    async def exists(self, key: str) -> bool:
        raise NotImplementedError("Subclasses must implement exists method")
    
    @abstractmethod
    async def clear(self) -> int:
        raise NotImplementedError("Subclasses must implement clear method")


@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime
    
    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at


class InMemoryCacheBackend(CacheBackend):
    def __init__(self, max_entries: int = 10000):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_entries = max_entries
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            
            if entry.is_expired:
                del self._cache[key]
                return None
            
            return entry.value
    
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        ttl = ttl_seconds or 3600
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        
        async with self._lock:
            if len(self._cache) >= self._max_entries:
                await self._evict_expired()
            
            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
            return True
    
    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def exists(self, key: str) -> bool:
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired:
                del self._cache[key]
                return False
            return True
    
    async def clear(self) -> int:
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count
    
    async def _evict_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired_keys = [k for k, v in self._cache.items() if v.expires_at < now]
        for key in expired_keys:
            del self._cache[key]
        
        if len(self._cache) >= self._max_entries:
            oldest_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k].expires_at)
            for key in oldest_keys[:len(self._cache) // 4]:
                del self._cache[key]


class RedisCacheBackend(CacheBackend):
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._client = None
    
    async def initialize(self) -> None:
        try:
            import redis.asyncio as redis
            self._client = redis.from_url(self._redis_url)
            logger.info("Redis cache backend initialized")
        except ImportError:
            logger.error("Redis library not installed")
            raise
    
    async def get(self, key: str) -> Optional[Any]:
        if not self._client:
            return None
        
        data = await self._client.get(key)
        if data:
            return json.loads(data)
        return None
    
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        if not self._client:
            return False
        
        serialized = json.dumps(value, default=str)
        if ttl_seconds:
            await self._client.set(key, serialized, ex=ttl_seconds)
        else:
            await self._client.set(key, serialized)
        return True
    
    async def delete(self, key: str) -> bool:
        if not self._client:
            return False
        return await self._client.delete(key) > 0
    
    async def exists(self, key: str) -> bool:
        if not self._client:
            return False
        return await self._client.exists(key) > 0
    
    async def clear(self) -> int:
        if not self._client:
            return 0
        return await self._client.flushdb()


class CacheManager:
    def __init__(self, config: Optional[CacheConfig] = None):
        self._config = config or CacheConfig()
        self._backend: Optional[CacheBackend] = None
        self._stats = {"hits": 0, "misses": 0, "sets": 0}
    
    async def initialize(self) -> None:
        if self._config.redis_url:
            try:
                backend = RedisCacheBackend(self._config.redis_url)
                await backend.initialize()
                self._backend = backend
            except Exception as e:
                logger.warning(f"Failed to initialize Redis cache: {e}, using in-memory")
                self._backend = InMemoryCacheBackend(self._config.max_entries)
        else:
            self._backend = InMemoryCacheBackend(self._config.max_entries)
        
        logger.info("Cache manager initialized")
    
    def _make_key(self, key: str) -> str:
        return f"{self._config.key_prefix}{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        if not self._backend:
            return None
        
        full_key = self._make_key(key)
        value = await self._backend.get(full_key)
        
        if value is not None:
            self._stats["hits"] += 1
        else:
            self._stats["misses"] += 1
        
        return value
    
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        if not self._backend:
            return False
        
        full_key = self._make_key(key)
        ttl = ttl_seconds or self._config.default_ttl_seconds
        result = await self._backend.set(full_key, value, ttl)
        
        if result:
            self._stats["sets"] += 1
        
        return result
    
    async def delete(self, key: str) -> bool:
        if not self._backend:
            return False
        return await self._backend.delete(self._make_key(key))
    
    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl_seconds: Optional[int] = None,
    ) -> Any:
        value = await self.get(key)
        if value is not None:
            return value
        
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()
        
        await self.set(key, value, ttl_seconds)
        return value
    
    async def invalidate_pattern(self, pattern: str) -> int:
        logger.debug(f"Pattern invalidation not fully supported: {pattern}")
        return 0
    
    def get_statistics(self) -> Dict[str, Any]:
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / max(total, 1)
        
        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "sets": self._stats["sets"],
            "hit_rate": hit_rate,
        }


def cached(key_template: str, ttl_seconds: int = 3600):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            cache = getattr(self, "_cache", None)
            if not cache:
                return await func(self, *args, **kwargs)
            
            cache_key = key_template.format(*args, **kwargs)
            
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            result = await func(self, *args, **kwargs)
            await cache.set(cache_key, result, ttl_seconds)
            return result
        
        return wrapper
    return decorator
