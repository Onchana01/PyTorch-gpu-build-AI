from typing import Optional, Callable
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.common.security.authentication import verify_jwt_token
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)

EXCLUDED_PATHS = {
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    "/api/v1/health",
    "/api/v1/ready",
    "/api/v1/webhooks/github",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self._is_excluded_path(request.url.path):
            return await call_next(request)
        
        if request.method == "OPTIONS":
            return await call_next(request)
        
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            settings = get_settings()
            if settings.debug:
                request.state.user = {"sub": "debug_user", "role": "admin"}
                return await call_next(request)
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        try:
            scheme, token = auth_header.split()
            if scheme.lower() != "bearer":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication scheme",
                )
            
            payload = verify_jwt_token(token)
            if not payload:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                )
            
            request.state.user = payload
            
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format",
            )
        
        return await call_next(request)
    
    def _is_excluded_path(self, path: str) -> bool:
        for excluded in EXCLUDED_PATHS:
            if path.startswith(excluded):
                return True
        return False
