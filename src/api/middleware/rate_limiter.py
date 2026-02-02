from typing import Dict, Callable
from datetime import datetime, timezone
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import asyncio

from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class TokenBucket:
    def __init__(self, rate: int, capacity: int):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = datetime.now(timezone.utc)
        self._lock = asyncio.Lock()
    
    async def consume(self, tokens: int = 1) -> bool:
        async with self._lock:
            now = datetime.now(timezone.utc)
            elapsed = (now - self.last_update).total_seconds()
            
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


class RateLimiter(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 100, burst_size: int = 20):
        super().__init__(app)
        self._rate = requests_per_minute / 60
        self._burst_size = burst_size
        self._buckets: Dict[str, TokenBucket] = {}
        self._cleanup_interval = 300
        self._last_cleanup = datetime.now(timezone.utc)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_id = self._get_client_id(request)
        
        if client_id not in self._buckets:
            self._buckets[client_id] = TokenBucket(self._rate, self._burst_size)
        
        bucket = self._buckets[client_id]
        
        if not await bucket.consume():
            logger.warning(f"Rate limit exceeded for client: {client_id}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": "60"},
            )
        
        await self._maybe_cleanup()
        
        response = await call_next(request)
        
        response.headers["X-RateLimit-Limit"] = str(int(self._rate * 60))
        response.headers["X-RateLimit-Remaining"] = str(int(bucket.tokens))
        
        return response
    
    def _get_client_id(self, request: Request) -> str:
        user = getattr(request.state, "user", None)
        if user and isinstance(user, dict):
            return user.get("sub", request.client.host if request.client else "unknown")
        
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        return request.client.host if request.client else "unknown"
    
    async def _maybe_cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        if (now - self._last_cleanup).total_seconds() > self._cleanup_interval:
            stale_clients = [
                client_id
                for client_id, bucket in self._buckets.items()
                if (now - bucket.last_update).total_seconds() > self._cleanup_interval
            ]
            for client_id in stale_clients:
                del self._buckets[client_id]
            self._last_cleanup = now
