from typing import Optional, Dict, Any, List
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.common.security.authentication import verify_jwt_token
from src.common.security.authorization import Permission, has_permission
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    if hasattr(request.state, "user") and request.state.user:
        return request.state.user
    
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    try:
        payload = verify_jwt_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return payload
        
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_permission(*permissions: Permission):
    async def permission_checker(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        user_role = user.get("role", "viewer")
        
        for permission in permissions:
            if not has_permission(user_role, permission):
                logger.warning(
                    f"Permission denied: user={user.get('sub')} role={user_role} required={permission.value}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: {permission.value} required",
                )
        
        return user
    
    return permission_checker


def require_admin():
    return require_permission(Permission.ADMIN)


def require_build_trigger():
    return require_permission(Permission.BUILD_TRIGGER)


def require_build_cancel():
    return require_permission(Permission.BUILD_CANCEL)


class CurrentUser:
    def __init__(self, user_data: Dict[str, Any]):
        self._data = user_data
    
    @property
    def user_id(self) -> str:
        return self._data.get("sub", "unknown")
    
    @property
    def email(self) -> Optional[str]:
        return self._data.get("email")
    
    @property
    def role(self) -> str:
        return self._data.get("role", "viewer")
    
    @property
    def permissions(self) -> List[str]:
        return self._data.get("permissions", [])
    
    def has_permission(self, permission: Permission) -> bool:
        return has_permission(self.role, permission)
    
    def to_dict(self) -> Dict[str, Any]:
        return self._data


async def get_current_user_model(
    user: Dict[str, Any] = Depends(get_current_user),
) -> CurrentUser:
    return CurrentUser(user)
