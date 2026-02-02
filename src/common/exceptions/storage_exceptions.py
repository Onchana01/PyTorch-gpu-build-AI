from typing import Optional, Dict, Any, List
from uuid import UUID

from src.common.exceptions.base_exceptions import (
    CICDBaseException,
    RetryableException,
    NonRetryableException,
    ErrorCode,
)


class StorageException(CICDBaseException):
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.STORAGE_ERROR,
        storage_type: Optional[str] = None,
        operation: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if storage_type:
            details["storage_type"] = storage_type
        if operation:
            details["operation"] = operation
        super().__init__(message, error_code, details, cause)
        self.storage_type = storage_type
        self.operation = operation


class DatabaseError(RetryableException):
    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        table_name: Optional[str] = None,
        query: Optional[str] = None,
        sql_state: Optional[str] = None,
        constraint_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if operation:
            details["operation"] = operation
        if table_name:
            details["table_name"] = table_name
        if query:
            details["query"] = query[:500]
        if sql_state:
            details["sql_state"] = sql_state
        if constraint_name:
            details["constraint_name"] = constraint_name
        super().__init__(
            message=message,
            error_code=ErrorCode.STORAGE_DATABASE_ERROR,
            details=details,
            cause=cause,
            max_retries=3,
            retry_delay_seconds=5,
        )
        self.operation = operation
        self.table_name = table_name
        self.query = query
        self.sql_state = sql_state
        self.constraint_name = constraint_name


class RecordNotFoundError(NonRetryableException):
    def __init__(
        self,
        message: str,
        record_id: Optional[str] = None,
        collection_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if record_id:
            details["record_id"] = record_id
        if collection_name:
            details["collection_name"] = collection_name
        super().__init__(
            message=message,
            error_code=ErrorCode.STORAGE_NOT_FOUND,
            details=details,
            cause=cause,
        )
        self.record_id = record_id
        self.collection_name = collection_name


class CacheError(RetryableException):
    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        cache_key: Optional[str] = None,
        cache_backend: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if operation:
            details["operation"] = operation
        if cache_key:
            details["cache_key"] = cache_key[:100]
        if cache_backend:
            details["cache_backend"] = cache_backend
        if ttl_seconds is not None:
            details["ttl_seconds"] = ttl_seconds
        super().__init__(
            message=message,
            error_code=ErrorCode.STORAGE_CACHE_ERROR,
            details=details,
            cause=cause,
            max_retries=3,
            retry_delay_seconds=2,
        )
        self.operation = operation
        self.cache_key = cache_key
        self.cache_backend = cache_backend
        self.ttl_seconds = ttl_seconds


class ArtifactStorageError(StorageException):
    def __init__(
        self,
        message: str,
        artifact_path: Optional[str] = None,
        artifact_id: Optional[UUID] = None,
        build_id: Optional[UUID] = None,
        bucket_name: Optional[str] = None,
        operation: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        checksum: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if artifact_path:
            details["artifact_path"] = artifact_path
        if artifact_id:
            details["artifact_id"] = str(artifact_id)
        if build_id:
            details["build_id"] = str(build_id)
        if bucket_name:
            details["bucket_name"] = bucket_name
        if file_size_bytes is not None:
            details["file_size_bytes"] = file_size_bytes
        if checksum:
            details["checksum"] = checksum
        super().__init__(
            message=message,
            error_code=ErrorCode.STORAGE_ARTIFACT_ERROR,
            storage_type="artifact",
            operation=operation,
            details=details,
            cause=cause,
        )
        self.artifact_path = artifact_path
        self.artifact_id = artifact_id
        self.build_id = build_id
        self.bucket_name = bucket_name
        self.file_size_bytes = file_size_bytes
        self.checksum = checksum


class StorageConnectionError(RetryableException):
    def __init__(
        self,
        message: str,
        storage_type: Optional[str] = None,
        endpoint: Optional[str] = None,
        port: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        connection_attempts: int = 0,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if storage_type:
            details["storage_type"] = storage_type
        if endpoint:
            details["endpoint"] = endpoint
        if port:
            details["port"] = port
        if timeout_seconds:
            details["timeout_seconds"] = timeout_seconds
        details["connection_attempts"] = connection_attempts
        super().__init__(
            message=message,
            error_code=ErrorCode.STORAGE_CONNECTION_ERROR,
            details=details,
            cause=cause,
            max_retries=5,
            retry_delay_seconds=10,
        )
        self.storage_type = storage_type
        self.endpoint = endpoint
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.connection_attempts = connection_attempts


class QuotaExceededError(NonRetryableException):
    def __init__(
        self,
        message: str,
        storage_type: Optional[str] = None,
        quota_limit: Optional[int] = None,
        current_usage: Optional[int] = None,
        requested_size: Optional[int] = None,
        resource_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if storage_type:
            details["storage_type"] = storage_type
        if quota_limit is not None:
            details["quota_limit"] = quota_limit
        if current_usage is not None:
            details["current_usage"] = current_usage
        if requested_size is not None:
            details["requested_size"] = requested_size
        if resource_type:
            details["resource_type"] = resource_type
        super().__init__(
            message=message,
            error_code=ErrorCode.STORAGE_QUOTA_EXCEEDED,
            details=details,
            cause=cause,
            requires_manual_intervention=True,
        )
        self.storage_type = storage_type
        self.quota_limit = quota_limit
        self.current_usage = current_usage
        self.requested_size = requested_size
        self.resource_type = resource_type

    @property
    def available_space(self) -> Optional[int]:
        if self.quota_limit is not None and self.current_usage is not None:
            return self.quota_limit - self.current_usage
        return None


class TransactionError(DatabaseError):
    def __init__(
        self,
        message: str,
        transaction_id: Optional[str] = None,
        operations: Optional[List[str]] = None,
        rollback_performed: bool = False,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if transaction_id:
            details["transaction_id"] = transaction_id
        if operations:
            details["operations"] = operations[:10]
        details["rollback_performed"] = rollback_performed
        super().__init__(
            message=message,
            operation="transaction",
            details=details,
            cause=cause,
        )
        self.transaction_id = transaction_id
        self.operations = operations or []
        self.rollback_performed = rollback_performed


class MigrationError(NonRetryableException):
    def __init__(
        self,
        message: str,
        migration_name: Optional[str] = None,
        migration_version: Optional[str] = None,
        direction: Optional[str] = None,
        failed_statement: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if migration_name:
            details["migration_name"] = migration_name
        if migration_version:
            details["migration_version"] = migration_version
        if direction:
            details["direction"] = direction
        if failed_statement:
            details["failed_statement"] = failed_statement[:500]
        super().__init__(
            message=message,
            error_code=ErrorCode.STORAGE_DATABASE_ERROR,
            details=details,
            cause=cause,
            requires_manual_intervention=True,
        )
        self.migration_name = migration_name
        self.migration_version = migration_version
        self.direction = direction
        self.failed_statement = failed_statement
