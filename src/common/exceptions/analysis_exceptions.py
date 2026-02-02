from typing import Optional, Dict, Any, List
from uuid import UUID

from src.common.exceptions.base_exceptions import (
    CICDBaseException,
    NonRetryableException,
    RetryableException,
    ErrorCode,
)


class AnalysisException(CICDBaseException):
    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.ANALYSIS_FAILED,
        failure_id: Optional[UUID] = None,
        build_id: Optional[UUID] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if failure_id:
            details["failure_id"] = str(failure_id)
        if build_id:
            details["build_id"] = str(build_id)
        super().__init__(message, error_code, details, cause)
        self.failure_id = failure_id
        self.build_id = build_id


class PatternMatchError(AnalysisException):
    def __init__(
        self,
        message: str,
        failure_id: Optional[UUID] = None,
        build_id: Optional[UUID] = None,
        pattern_id: Optional[str] = None,
        error_message: Optional[str] = None,
        attempted_patterns: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if pattern_id:
            details["pattern_id"] = pattern_id
        if error_message:
            details["error_message"] = error_message[:500]
        if attempted_patterns:
            details["attempted_patterns"] = attempted_patterns[:20]
        super().__init__(
            message=message,
            error_code=ErrorCode.ANALYSIS_PATTERN_NOT_FOUND,
            failure_id=failure_id,
            build_id=build_id,
            details=details,
            cause=cause,
        )
        self.pattern_id = pattern_id
        self.error_message = error_message
        self.attempted_patterns = attempted_patterns or []


class RootCauseNotFound(AnalysisException):
    def __init__(
        self,
        message: str = "Could not determine root cause",
        failure_id: Optional[UUID] = None,
        build_id: Optional[UUID] = None,
        analysis_methods_tried: Optional[List[str]] = None,
        partial_findings: Optional[Dict[str, Any]] = None,
        suggested_investigation: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if analysis_methods_tried:
            details["analysis_methods_tried"] = analysis_methods_tried
        if partial_findings:
            details["partial_findings"] = partial_findings
        if suggested_investigation:
            details["suggested_investigation"] = suggested_investigation
        super().__init__(
            message=message,
            error_code=ErrorCode.ANALYSIS_ROOT_CAUSE_NOT_FOUND,
            failure_id=failure_id,
            build_id=build_id,
            details=details,
            cause=cause,
        )
        self.analysis_methods_tried = analysis_methods_tried or []
        self.partial_findings = partial_findings
        self.suggested_investigation = suggested_investigation


class RecommendationError(AnalysisException):
    def __init__(
        self,
        message: str,
        failure_id: Optional[UUID] = None,
        build_id: Optional[UUID] = None,
        recommendation_stage: Optional[str] = None,
        available_fixes: int = 0,
        matching_criteria: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if recommendation_stage:
            details["recommendation_stage"] = recommendation_stage
        details["available_fixes"] = available_fixes
        if matching_criteria:
            details["matching_criteria"] = matching_criteria
        super().__init__(
            message=message,
            error_code=ErrorCode.ANALYSIS_RECOMMENDATION_ERROR,
            failure_id=failure_id,
            build_id=build_id,
            details=details,
            cause=cause,
        )
        self.recommendation_stage = recommendation_stage
        self.available_fixes = available_fixes
        self.matching_criteria = matching_criteria


class LogParsingError(AnalysisException):
    def __init__(
        self,
        message: str,
        failure_id: Optional[UUID] = None,
        build_id: Optional[UUID] = None,
        log_file: Optional[str] = None,
        log_format: Optional[str] = None,
        line_number: Optional[int] = None,
        parse_error: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if log_file:
            details["log_file"] = log_file
        if log_format:
            details["log_format"] = log_format
        if line_number:
            details["line_number"] = line_number
        if parse_error:
            details["parse_error"] = parse_error[:500]
        super().__init__(
            message=message,
            error_code=ErrorCode.ANALYSIS_LOG_PARSING_ERROR,
            failure_id=failure_id,
            build_id=build_id,
            details=details,
            cause=cause,
        )
        self.log_file = log_file
        self.log_format = log_format
        self.line_number = line_number
        self.parse_error = parse_error


class KnowledgeBaseError(RetryableException):
    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        query: Optional[str] = None,
        affected_records: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if operation:
            details["operation"] = operation
        if query:
            details["query"] = query[:200]
        if affected_records is not None:
            details["affected_records"] = affected_records
        super().__init__(
            message=message,
            error_code=ErrorCode.ANALYSIS_KNOWLEDGE_BASE_ERROR,
            details=details,
            cause=cause,
            max_retries=3,
            retry_delay_seconds=10,
        )
        self.operation = operation
        self.query = query
        self.affected_records = affected_records


class ClassificationError(AnalysisException):
    def __init__(
        self,
        message: str,
        failure_id: Optional[UUID] = None,
        build_id: Optional[UUID] = None,
        attempted_classifications: Optional[List[str]] = None,
        confidence_scores: Optional[Dict[str, float]] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if attempted_classifications:
            details["attempted_classifications"] = attempted_classifications
        if confidence_scores:
            details["confidence_scores"] = confidence_scores
        super().__init__(
            message=message,
            error_code=ErrorCode.ANALYSIS_FAILED,
            failure_id=failure_id,
            build_id=build_id,
            details=details,
            cause=cause,
        )
        self.attempted_classifications = attempted_classifications or []
        self.confidence_scores = confidence_scores


class SimilaritySearchError(AnalysisException):
    def __init__(
        self,
        message: str,
        failure_id: Optional[UUID] = None,
        build_id: Optional[UUID] = None,
        search_query: Optional[str] = None,
        search_space_size: Optional[int] = None,
        threshold: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        details = details or {}
        if search_query:
            details["search_query"] = search_query[:200]
        if search_space_size is not None:
            details["search_space_size"] = search_space_size
        if threshold is not None:
            details["threshold"] = threshold
        super().__init__(
            message=message,
            error_code=ErrorCode.ANALYSIS_FAILED,
            failure_id=failure_id,
            build_id=build_id,
            details=details,
            cause=cause,
        )
        self.search_query = search_query
        self.search_space_size = search_space_size
        self.threshold = threshold
