from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from src.common.dto.base import BaseDTO, TimestampMixin
from src.common.config.constants import FailureCategory, SeverityLevel


class StackFrame(BaseModel):
    file_path: str
    line_number: int
    column_number: Optional[int] = None
    function_name: Optional[str] = None
    class_name: Optional[str] = None
    code_context: Optional[str] = None
    is_project_code: bool = Field(default=True)


class ErrorSignature(BaseModel):
    signature_hash: str = Field(description="Hash of normalized error message")
    raw_message: str
    normalized_message: str
    error_code: Optional[str] = None
    error_type: Optional[str] = None
    component: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)

    @computed_field
    @property
    def short_signature(self) -> str:
        return self.signature_hash[:12]


class FailureContext(BaseModel):
    build_stage: str = Field(description="Stage where failure occurred")
    log_file_path: Optional[str] = None
    log_line_start: Optional[int] = None
    log_line_end: Optional[int] = None
    log_excerpt: Optional[str] = None
    stack_trace: List[StackFrame] = Field(default_factory=list)
    environment_variables: Dict[str, str] = Field(default_factory=dict)
    cmake_cache_variables: Dict[str, str] = Field(default_factory=dict)
    compiler_invocation: Optional[str] = None
    working_directory: Optional[str] = None
    preceding_commands: List[str] = Field(default_factory=list)


class FailureClassification(BaseModel):
    primary_category: FailureCategory
    secondary_category: Optional[FailureCategory] = None
    severity: SeverityLevel = Field(default=SeverityLevel.ERROR)
    affected_component: Optional[str] = None
    affected_files: List[str] = Field(default_factory=list)
    is_flaky: bool = Field(default=False)
    is_infrastructure_related: bool = Field(default=False)
    is_user_error: bool = Field(default=False)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)


class RootCauseAnalysis(BaseModel):
    primary_cause: str
    cause_description: str
    confidence: float = Field(ge=0.0, le=1.0)
    contributing_factors: List[str] = Field(default_factory=list)
    environmental_factors: Dict[str, str] = Field(default_factory=dict)
    similar_failure_ids: List[UUID] = Field(default_factory=list)
    causal_chain: List[str] = Field(default_factory=list)
    analysis_method: str = Field(default="pattern_matching")


class FailureRecord(BaseDTO):
    build_id: UUID
    build_configuration_hash: str
    signature: ErrorSignature
    context: FailureContext
    classification: FailureClassification
    root_cause_analysis: Optional[RootCauseAnalysis] = None
    rocm_version: str
    gpu_architecture: str
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resolved: bool = Field(default=False)
    resolution_notes: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by_fix_id: Optional[UUID] = None
    occurrence_count: int = Field(default=1)
    first_seen: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_seen: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    related_pr_numbers: List[int] = Field(default_factory=list)
    related_commit_shas: List[str] = Field(default_factory=list)

    def mark_resolved(
        self,
        fix_id: Optional[UUID] = None,
        notes: Optional[str] = None
    ) -> None:
        self.resolved = True
        self.resolved_at = datetime.now(timezone.utc)
        self.resolved_by_fix_id = fix_id
        self.resolution_notes = notes
        self.touch()

    def increment_occurrence(self) -> None:
        self.occurrence_count += 1
        self.last_seen = datetime.now(timezone.utc)
        self.touch()


class FailureSummary(BaseModel):
    failure_id: UUID
    category: FailureCategory
    severity: SeverityLevel
    short_message: str
    component: Optional[str] = None
    occurrence_count: int = Field(default=1)
    has_recommended_fix: bool = Field(default=False)
    confidence_score: float = Field(default=0.0)


class FailureStatistics(BaseModel):
    total_failures: int = Field(default=0)
    by_category: Dict[str, int] = Field(default_factory=dict)
    by_severity: Dict[str, int] = Field(default_factory=dict)
    by_component: Dict[str, int] = Field(default_factory=dict)
    by_rocm_version: Dict[str, int] = Field(default_factory=dict)
    by_gpu_architecture: Dict[str, int] = Field(default_factory=dict)
    resolution_rate: float = Field(default=0.0)
    average_time_to_resolution_hours: float = Field(default=0.0)
    most_common_failures: List[FailureSummary] = Field(default_factory=list)
    trending_failures: List[FailureSummary] = Field(default_factory=list)


class FailurePattern(BaseModel):
    pattern_id: str
    pattern_name: str
    pattern_regex: str
    category: FailureCategory
    description: str
    recommended_fix_ids: List[str] = Field(default_factory=list)
    match_count: int = Field(default=0)
    last_matched: Optional[datetime] = None
    is_active: bool = Field(default=True)
    priority: int = Field(default=0)
