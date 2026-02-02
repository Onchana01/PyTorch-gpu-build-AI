from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone


class ErrorCode(str, Enum):
    UNKNOWN = "E0000"
    
    BUILD_FAILED = "E1000"
    BUILD_CONFIGURATION_ERROR = "E1001"
    BUILD_COMPILATION_ERROR = "E1002"
    BUILD_LINKING_ERROR = "E1003"
    BUILD_TEST_FAILED = "E1004"
    BUILD_TIMEOUT = "E1005"
    BUILD_CANCELLED = "E1006"
    BUILD_ENVIRONMENT_ERROR = "E1007"
    BUILD_RESOURCE_ERROR = "E1008"
    
    ANALYSIS_FAILED = "E2000"
    ANALYSIS_PATTERN_NOT_FOUND = "E2001"
    ANALYSIS_ROOT_CAUSE_NOT_FOUND = "E2002"
    ANALYSIS_RECOMMENDATION_ERROR = "E2003"
    ANALYSIS_LOG_PARSING_ERROR = "E2004"
    ANALYSIS_KNOWLEDGE_BASE_ERROR = "E2005"
    
    STORAGE_ERROR = "E3000"
    STORAGE_DATABASE_ERROR = "E3001"
    STORAGE_CACHE_ERROR = "E3002"
    STORAGE_ARTIFACT_ERROR = "E3003"
    STORAGE_CONNECTION_ERROR = "E3004"
    STORAGE_QUOTA_EXCEEDED = "E3005"
    STORAGE_NOT_FOUND = "E3006"
    
    NOTIFICATION_ERROR = "E4000"
    NOTIFICATION_DELIVERY_FAILED = "E4001"
    NOTIFICATION_RATE_LIMITED = "E4002"
    
    INFRASTRUCTURE_ERROR = "E5000"
    INFRASTRUCTURE_GPU_ERROR = "E5001"
    INFRASTRUCTURE_KUBERNETES_ERROR = "E5002"
    INFRASTRUCTURE_DOCKER_ERROR = "E5003"
    
    AUTHENTICATION_ERROR = "E6000"
    AUTHORIZATION_ERROR = "E6001"
    TOKEN_EXPIRED = "E6002"
    INVALID_CREDENTIALS = "E6003"
    
    VALIDATION_ERROR = "E7000"
    INVALID_INPUT = "E7001"
    MISSING_REQUIRED_FIELD = "E7002"
    
    EXTERNAL_SERVICE_ERROR = "E8000"
    GITHUB_API_ERROR = "E8001"
    SLACK_API_ERROR = "E8002"
    VAULT_ERROR = "E8003"


class CICDBaseException(Exception):
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause
        self.timestamp = datetime.now(timezone.utc)

    def __str__(self) -> str:
        return f"[{self.error_code.value}] {self.message}"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"error_code={self.error_code}, "
            f"details={self.details})"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "exception_type": self.__class__.__name__,
        }

    def with_context(self, **kwargs: Any) -> "CICDBaseException":
        self.details.update(kwargs)
        return self


class RetryableException(CICDBaseException):
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        max_retries: int = 3,
        retry_delay_seconds: int = 30,
    ):
        super().__init__(message, error_code, details, cause)
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.retry_count = 0

    def should_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def increment_retry(self) -> None:
        self.retry_count += 1

    def get_retry_delay(self) -> int:
        return self.retry_delay_seconds * (2 ** self.retry_count)


class NonRetryableException(CICDBaseException):
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        requires_manual_intervention: bool = False,
    ):
        super().__init__(message, error_code, details, cause)
        self.requires_manual_intervention = requires_manual_intervention


class ValidationException(NonRetryableException):
    def __init__(
        self,
        message: str,
        field_name: Optional[str] = None,
        field_value: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = details or {}
        if field_name:
            details["field_name"] = field_name
        if field_value is not None:
            details["field_value"] = str(field_value)
        super().__init__(
            message=message,
            error_code=ErrorCode.VALIDATION_ERROR,
            details=details,
        )
        self.field_name = field_name
        self.field_value = field_value


class AuthenticationException(NonRetryableException):
    def __init__(
        self,
        message: str = "Authentication failed",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            error_code=ErrorCode.AUTHENTICATION_ERROR,
            details=details,
        )


class AuthorizationException(NonRetryableException):
    def __init__(
        self,
        message: str = "Access denied",
        required_permission: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = details or {}
        if required_permission:
            details["required_permission"] = required_permission
        super().__init__(
            message=message,
            error_code=ErrorCode.AUTHORIZATION_ERROR,
            details=details,
        )
        self.required_permission = required_permission


class ExternalServiceException(RetryableException):
    def __init__(
        self,
        service_name: str,
        message: str,
        error_code: ErrorCode = ErrorCode.EXTERNAL_SERVICE_ERROR,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = details or {}
        details["service_name"] = service_name
        if status_code:
            details["status_code"] = status_code
        if response_body:
            details["response_body"] = response_body[:500]
        super().__init__(
            message=f"{service_name}: {message}",
            error_code=error_code,
            details=details,
        )
        self.service_name = service_name
        self.status_code = status_code
        self.response_body = response_body
