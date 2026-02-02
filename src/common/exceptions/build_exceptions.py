from typing import Optional, Dict, Any, List
from uuid import UUID

from src.common.exceptions.base_exceptions import (
    CICDBaseException,
    RetryableException,
    NonRetryableException,
    ErrorCode,
)


class BuildException(CICDBaseException):
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.BUILD_FAILED,
        build_id: Optional[UUID] = None,
        stage: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if build_id:
            details["build_id"] = str(build_id)
        if stage:
            details["stage"] = stage
        super().__init__(message, error_code, details, cause)
        self.build_id = build_id
        self.stage = stage


class BuildFailedException(BuildException):
    def __init__(
        self,
        message: str,
        build_id: Optional[UUID] = None,
        stage: Optional[str] = None,
        exit_code: Optional[int] = None,
        log_excerpt: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if exit_code is not None:
            details["exit_code"] = exit_code
        if log_excerpt:
            details["log_excerpt"] = log_excerpt[:1000]
        super().__init__(
            message=message,
            error_code=ErrorCode.BUILD_FAILED,
            build_id=build_id,
            stage=stage,
            details=details,
            cause=cause,
        )
        self.exit_code = exit_code
        self.log_excerpt = log_excerpt


class ConfigurationError(BuildException):
    def __init__(
        self,
        message: str,
        build_id: Optional[UUID] = None,
        config_file: Optional[str] = None,
        missing_dependencies: Optional[List[str]] = None,
        cmake_error: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if config_file:
            details["config_file"] = config_file
        if missing_dependencies:
            details["missing_dependencies"] = missing_dependencies
        if cmake_error:
            details["cmake_error"] = cmake_error[:500]
        super().__init__(
            message=message,
            error_code=ErrorCode.BUILD_CONFIGURATION_ERROR,
            build_id=build_id,
            stage="configuration",
            details=details,
            cause=cause,
        )
        self.config_file = config_file
        self.missing_dependencies = missing_dependencies or []
        self.cmake_error = cmake_error


class CompilationError(BuildException):
    def __init__(
        self,
        message: str,
        build_id: Optional[UUID] = None,
        source_file: Optional[str] = None,
        line_number: Optional[int] = None,
        column_number: Optional[int] = None,
        error_type: Optional[str] = None,
        compiler_output: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if source_file:
            details["source_file"] = source_file
        if line_number:
            details["line_number"] = line_number
        if column_number:
            details["column_number"] = column_number
        if error_type:
            details["error_type"] = error_type
        if compiler_output:
            details["compiler_output"] = compiler_output[:1000]
        super().__init__(
            message=message,
            error_code=ErrorCode.BUILD_COMPILATION_ERROR,
            build_id=build_id,
            stage="compilation",
            details=details,
            cause=cause,
        )
        self.source_file = source_file
        self.line_number = line_number
        self.column_number = column_number
        self.error_type = error_type
        self.compiler_output = compiler_output

    @property
    def location(self) -> str:
        if self.source_file:
            loc = self.source_file
            if self.line_number:
                loc += f":{self.line_number}"
                if self.column_number:
                    loc += f":{self.column_number}"
            return loc
        return "unknown"


class LinkingError(BuildException):
    def __init__(
        self,
        message: str,
        build_id: Optional[UUID] = None,
        undefined_symbols: Optional[List[str]] = None,
        missing_libraries: Optional[List[str]] = None,
        linker_output: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if undefined_symbols:
            details["undefined_symbols"] = undefined_symbols[:20]
        if missing_libraries:
            details["missing_libraries"] = missing_libraries
        if linker_output:
            details["linker_output"] = linker_output[:1000]
        super().__init__(
            message=message,
            error_code=ErrorCode.BUILD_LINKING_ERROR,
            build_id=build_id,
            stage="linking",
            details=details,
            cause=cause,
        )
        self.undefined_symbols = undefined_symbols or []
        self.missing_libraries = missing_libraries or []
        self.linker_output = linker_output


class TestFailedException(BuildException):
    def __init__(
        self,
        message: str,
        build_id: Optional[UUID] = None,
        test_name: Optional[str] = None,
        test_class: Optional[str] = None,
        failed_tests: Optional[List[str]] = None,
        passed_count: int = 0,
        failed_count: int = 0,
        total_count: int = 0,
        test_output: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if test_name:
            details["test_name"] = test_name
        if test_class:
            details["test_class"] = test_class
        if failed_tests:
            details["failed_tests"] = failed_tests[:50]
        details["passed_count"] = passed_count
        details["failed_count"] = failed_count
        details["total_count"] = total_count
        if test_output:
            details["test_output"] = test_output[:1000]
        super().__init__(
            message=message,
            error_code=ErrorCode.BUILD_TEST_FAILED,
            build_id=build_id,
            stage="testing",
            details=details,
            cause=cause,
        )
        self.test_name = test_name
        self.test_class = test_class
        self.failed_tests = failed_tests or []
        self.passed_count = passed_count
        self.failed_count = failed_count
        self.total_count = total_count
        self.test_output = test_output

    @property
    def pass_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.passed_count / self.total_count


class BuildTimeoutException(RetryableException):
    def __init__(
        self,
        message: str,
        build_id: Optional[UUID] = None,
        stage: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        elapsed_seconds: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if build_id:
            details["build_id"] = str(build_id)
        if stage:
            details["stage"] = stage
        if timeout_seconds:
            details["timeout_seconds"] = timeout_seconds
        if elapsed_seconds:
            details["elapsed_seconds"] = elapsed_seconds
        super().__init__(
            message=message,
            error_code=ErrorCode.BUILD_TIMEOUT,
            details=details,
            cause=cause,
            max_retries=1,
            retry_delay_seconds=60,
        )
        self.build_id = build_id
        self.stage = stage
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds


class BuildCancelledException(NonRetryableException):
    def __init__(
        self,
        message: str = "Build was cancelled",
        build_id: Optional[UUID] = None,
        cancelled_by: Optional[str] = None,
        reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        details = details or {}
        if build_id:
            details["build_id"] = str(build_id)
        if cancelled_by:
            details["cancelled_by"] = cancelled_by
        if reason:
            details["reason"] = reason
        super().__init__(
            message=message,
            error_code=ErrorCode.BUILD_CANCELLED,
            details=details,
            requires_manual_intervention=False,
        )
        self.build_id = build_id
        self.cancelled_by = cancelled_by
        self.reason = reason


class EnvironmentError(BuildException):
    def __init__(
        self,
        message: str,
        build_id: Optional[UUID] = None,
        missing_tools: Optional[List[str]] = None,
        missing_environment_variables: Optional[List[str]] = None,
        rocm_issue: Optional[str] = None,
        gpu_issue: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if missing_tools:
            details["missing_tools"] = missing_tools
        if missing_environment_variables:
            details["missing_environment_variables"] = missing_environment_variables
        if rocm_issue:
            details["rocm_issue"] = rocm_issue
        if gpu_issue:
            details["gpu_issue"] = gpu_issue
        super().__init__(
            message=message,
            error_code=ErrorCode.BUILD_ENVIRONMENT_ERROR,
            build_id=build_id,
            stage="environment_setup",
            details=details,
            cause=cause,
        )
        self.missing_tools = missing_tools or []
        self.missing_environment_variables = missing_environment_variables or []
        self.rocm_issue = rocm_issue
        self.gpu_issue = gpu_issue


class ResourceExhaustionError(RetryableException):
    def __init__(
        self,
        message: str,
        build_id: Optional[UUID] = None,
        resource_type: Optional[str] = None,
        requested: Optional[float] = None,
        available: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if build_id:
            details["build_id"] = str(build_id)
        if resource_type:
            details["resource_type"] = resource_type
        if requested is not None:
            details["requested"] = requested
        if available is not None:
            details["available"] = available
        super().__init__(
            message=message,
            error_code=ErrorCode.BUILD_RESOURCE_ERROR,
            details=details,
            cause=cause,
            max_retries=3,
            retry_delay_seconds=120,
        )
        self.build_id = build_id
        self.resource_type = resource_type
        self.requested = requested
        self.available = available
