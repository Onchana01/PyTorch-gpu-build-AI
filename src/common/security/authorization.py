from enum import Enum, Flag, auto
from typing import List, Set, Optional, Callable, Any
from functools import wraps

from src.common.exceptions.base_exceptions import AuthorizationException


class Permission(Flag):
    NONE = 0
    
    BUILD_VIEW = auto()
    BUILD_CREATE = auto()
    BUILD_CANCEL = auto()
    BUILD_RETRY = auto()
    BUILD_DELETE = auto()
    BUILD_ADMIN = BUILD_VIEW | BUILD_CREATE | BUILD_CANCEL | BUILD_RETRY | BUILD_DELETE
    
    TEST_VIEW = auto()
    TEST_RUN = auto()
    TEST_SKIP = auto()
    TEST_QUARANTINE = auto()
    TEST_ADMIN = TEST_VIEW | TEST_RUN | TEST_SKIP | TEST_QUARANTINE
    
    ANALYSIS_VIEW = auto()
    ANALYSIS_CREATE = auto()
    ANALYSIS_UPDATE = auto()
    ANALYSIS_DELETE = auto()
    ANALYSIS_ADMIN = ANALYSIS_VIEW | ANALYSIS_CREATE | ANALYSIS_UPDATE | ANALYSIS_DELETE
    
    FIX_VIEW = auto()
    FIX_CREATE = auto()
    FIX_UPDATE = auto()
    FIX_DELETE = auto()
    FIX_APPLY = auto()
    FIX_ADMIN = FIX_VIEW | FIX_CREATE | FIX_UPDATE | FIX_DELETE | FIX_APPLY
    
    CONFIG_VIEW = auto()
    CONFIG_UPDATE = auto()
    CONFIG_ADMIN = CONFIG_VIEW | CONFIG_UPDATE
    
    USER_VIEW = auto()
    USER_CREATE = auto()
    USER_UPDATE = auto()
    USER_DELETE = auto()
    USER_ADMIN = USER_VIEW | USER_CREATE | USER_UPDATE | USER_DELETE
    
    NOTIFICATION_VIEW = auto()
    NOTIFICATION_SEND = auto()
    NOTIFICATION_ADMIN = NOTIFICATION_VIEW | NOTIFICATION_SEND
    
    METRICS_VIEW = auto()
    METRICS_EXPORT = auto()
    METRICS_ADMIN = METRICS_VIEW | METRICS_EXPORT
    
    INFRASTRUCTURE_VIEW = auto()
    INFRASTRUCTURE_MANAGE = auto()
    INFRASTRUCTURE_ADMIN = INFRASTRUCTURE_VIEW | INFRASTRUCTURE_MANAGE
    
    SYSTEM_ADMIN = auto()


class Role(str, Enum):
    ANONYMOUS = "anonymous"
    VIEWER = "viewer"
    DEVELOPER = "developer"
    MAINTAINER = "maintainer"
    ADMIN = "admin"
    SERVICE_ACCOUNT = "service_account"
    SUPER_ADMIN = "super_admin"


ROLE_PERMISSIONS: dict[Role, Permission] = {
    Role.ANONYMOUS: Permission.BUILD_VIEW | Permission.TEST_VIEW,
    
    Role.VIEWER: (
        Permission.BUILD_VIEW |
        Permission.TEST_VIEW |
        Permission.ANALYSIS_VIEW |
        Permission.FIX_VIEW |
        Permission.METRICS_VIEW
    ),
    
    Role.DEVELOPER: (
        Permission.BUILD_VIEW |
        Permission.BUILD_CREATE |
        Permission.BUILD_CANCEL |
        Permission.BUILD_RETRY |
        Permission.TEST_VIEW |
        Permission.TEST_RUN |
        Permission.ANALYSIS_VIEW |
        Permission.ANALYSIS_CREATE |
        Permission.FIX_VIEW |
        Permission.FIX_APPLY |
        Permission.NOTIFICATION_VIEW |
        Permission.METRICS_VIEW
    ),
    
    Role.MAINTAINER: (
        Permission.BUILD_ADMIN |
        Permission.TEST_ADMIN |
        Permission.ANALYSIS_ADMIN |
        Permission.FIX_ADMIN |
        Permission.CONFIG_VIEW |
        Permission.NOTIFICATION_ADMIN |
        Permission.METRICS_ADMIN |
        Permission.INFRASTRUCTURE_VIEW
    ),
    
    Role.ADMIN: (
        Permission.BUILD_ADMIN |
        Permission.TEST_ADMIN |
        Permission.ANALYSIS_ADMIN |
        Permission.FIX_ADMIN |
        Permission.CONFIG_ADMIN |
        Permission.USER_ADMIN |
        Permission.NOTIFICATION_ADMIN |
        Permission.METRICS_ADMIN |
        Permission.INFRASTRUCTURE_ADMIN
    ),
    
    Role.SERVICE_ACCOUNT: (
        Permission.BUILD_ADMIN |
        Permission.TEST_ADMIN |
        Permission.ANALYSIS_ADMIN |
        Permission.FIX_VIEW |
        Permission.FIX_APPLY |
        Permission.NOTIFICATION_SEND |
        Permission.METRICS_VIEW |
        Permission.METRICS_EXPORT
    ),
    
    Role.SUPER_ADMIN: Permission.SYSTEM_ADMIN,
}


class PermissionSet:
    def __init__(self, permissions: Permission = Permission.NONE):
        self._permissions = permissions
    
    @classmethod
    def from_roles(cls, roles: List[Role]) -> "PermissionSet":
        combined = Permission.NONE
        for role in roles:
            if role in ROLE_PERMISSIONS:
                combined |= ROLE_PERMISSIONS[role]
        return cls(combined)
    
    @classmethod
    def from_permission_names(cls, permission_names: List[str]) -> "PermissionSet":
        combined = Permission.NONE
        for name in permission_names:
            try:
                perm = Permission[name.upper()]
                combined |= perm
            except KeyError:
                continue
        return cls(combined)
    
    def has(self, permission: Permission) -> bool:
        if Permission.SYSTEM_ADMIN in self._permissions:
            return True
        return (self._permissions & permission) == permission
    
    def has_any(self, *permissions: Permission) -> bool:
        for permission in permissions:
            if self.has(permission):
                return True
        return False
    
    def has_all(self, *permissions: Permission) -> bool:
        for permission in permissions:
            if not self.has(permission):
                return False
        return True
    
    def add(self, permission: Permission) -> None:
        self._permissions |= permission
    
    def remove(self, permission: Permission) -> None:
        self._permissions &= ~permission
    
    def to_list(self) -> List[str]:
        return [p.name for p in Permission if p in self._permissions and p != Permission.NONE]
    
    @property
    def permissions(self) -> Permission:
        return self._permissions


def get_role_permissions(role: Role) -> Permission:
    return ROLE_PERMISSIONS.get(role, Permission.NONE)


def has_permission(
    user_permissions: PermissionSet,
    required_permission: Permission,
) -> bool:
    return user_permissions.has(required_permission)


def require_permission(
    *required_permissions: Permission,
    require_all: bool = True,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            permission_set: Optional[PermissionSet] = kwargs.get("permission_set")
            
            if permission_set is None:
                for arg in args:
                    if isinstance(arg, PermissionSet):
                        permission_set = arg
                        break
            
            if permission_set is None:
                raise AuthorizationException(
                    message="No permission set provided",
                    required_permission=", ".join(p.name for p in required_permissions),
                )
            
            if require_all:
                if not permission_set.has_all(*required_permissions):
                    raise AuthorizationException(
                        message="Insufficient permissions",
                        required_permission=", ".join(p.name for p in required_permissions),
                    )
            else:
                if not permission_set.has_any(*required_permissions):
                    raise AuthorizationException(
                        message="Insufficient permissions",
                        required_permission=", ".join(p.name for p in required_permissions),
                    )
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


class ResourceAccessControl:
    def __init__(self):
        self._resource_permissions: dict[str, dict[str, Permission]] = {}
    
    def set_resource_permission(
        self,
        resource_type: str,
        resource_id: str,
        permission: Permission,
    ) -> None:
        if resource_type not in self._resource_permissions:
            self._resource_permissions[resource_type] = {}
        self._resource_permissions[resource_type][resource_id] = permission
    
    def get_resource_permission(
        self,
        resource_type: str,
        resource_id: str,
    ) -> Permission:
        return self._resource_permissions.get(resource_type, {}).get(
            resource_id, Permission.NONE
        )
    
    def check_access(
        self,
        user_permissions: PermissionSet,
        resource_type: str,
        resource_id: str,
        required_permission: Permission,
    ) -> bool:
        if user_permissions.has(Permission.SYSTEM_ADMIN):
            return True
        
        if not user_permissions.has(required_permission):
            return False
        
        resource_perm = self.get_resource_permission(resource_type, resource_id)
        if resource_perm == Permission.NONE:
            return True
        
        return user_permissions.has(resource_perm)
