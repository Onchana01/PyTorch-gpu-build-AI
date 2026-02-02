from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, computed_field

from src.common.dto.base import BaseDTO, TimestampMixin
from src.common.config.constants import FixType, ROCmVersion, GPUArchitecture


class ApplicabilityCondition(BaseModel):
    rocm_versions: List[str] = Field(default_factory=list)
    gpu_architectures: List[str] = Field(default_factory=list)
    os_versions: List[str] = Field(default_factory=list)
    compiler_versions: List[str] = Field(default_factory=list)
    python_versions: List[str] = Field(default_factory=list)
    required_environment_variables: Dict[str, str] = Field(default_factory=dict)
    excluded_environments: List[str] = Field(default_factory=list)

    def is_applicable(
        self,
        rocm_version: str,
        gpu_arch: str,
        os_version: Optional[str] = None,
        compiler_version: Optional[str] = None,
        python_version: Optional[str] = None
    ) -> bool:
        if self.rocm_versions and rocm_version not in self.rocm_versions:
            return False
        if self.gpu_architectures and gpu_arch not in self.gpu_architectures:
            return False
        if self.os_versions and os_version and os_version not in self.os_versions:
            return False
        if self.compiler_versions and compiler_version and compiler_version not in self.compiler_versions:
            return False
        if self.python_versions and python_version and python_version not in self.python_versions:
            return False
        return True


class FixStep(BaseModel):
    order: int = Field(ge=0)
    description: str
    command: Optional[str] = None
    file_to_modify: Optional[str] = None
    content_before: Optional[str] = None
    content_after: Optional[str] = None
    environment_variable: Optional[str] = None
    environment_value: Optional[str] = None
    verification_command: Optional[str] = None
    expected_output: Optional[str] = None
    rollback_command: Optional[str] = None
    timeout_seconds: int = Field(default=300)
    requires_sudo: bool = Field(default=False)
    is_optional: bool = Field(default=False)

    @computed_field
    @property
    def step_type(self) -> str:
        if self.command:
            return "command"
        elif self.file_to_modify:
            return "file_modification"
        elif self.environment_variable:
            return "environment"
        return "unknown"


class FixEffectiveness(BaseModel):
    total_applications: int = Field(default=0)
    successful_applications: int = Field(default=0)
    failed_applications: int = Field(default=0)
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    average_application_time_seconds: float = Field(default=0.0)
    last_successful_application: Optional[datetime] = None
    last_failed_application: Optional[datetime] = None
    user_feedback_positive: int = Field(default=0)
    user_feedback_negative: int = Field(default=0)
    expert_validated: bool = Field(default=False)
    validation_date: Optional[datetime] = None

    def record_application(self, success: bool, duration_seconds: float) -> None:
        self.total_applications += 1
        if success:
            self.successful_applications += 1
            self.last_successful_application = datetime.now(timezone.utc)
        else:
            self.failed_applications += 1
            self.last_failed_application = datetime.now(timezone.utc)
        
        total_time = self.average_application_time_seconds * (self.total_applications - 1)
        self.average_application_time_seconds = (total_time + duration_seconds) / self.total_applications
        self.success_rate = self.successful_applications / self.total_applications


class FixRecord(BaseDTO):
    name: str
    description: str
    fix_type: FixType
    failure_signature_hashes: List[str] = Field(default_factory=list)
    failure_categories: List[str] = Field(default_factory=list)
    steps: List[FixStep] = Field(default_factory=list)
    applicability: ApplicabilityCondition = Field(
        default_factory=ApplicabilityCondition
    )
    effectiveness: FixEffectiveness = Field(default_factory=FixEffectiveness)
    documentation_url: Optional[str] = None
    related_fix_ids: List[UUID] = Field(default_factory=list)
    supersedes_fix_ids: List[UUID] = Field(default_factory=list)
    is_deprecated: bool = Field(default=False)
    deprecation_reason: Optional[str] = None
    author: Optional[str] = None
    reviewed_by: Optional[str] = None

    @computed_field
    @property
    def is_quick_fix(self) -> bool:
        return len(self.steps) <= 2 and all(
            step.timeout_seconds <= 60 for step in self.steps
        )

    @computed_field
    @property
    def estimated_effort_minutes(self) -> int:
        base_time = sum(step.timeout_seconds for step in self.steps) / 60
        if any(step.requires_sudo for step in self.steps):
            base_time *= 1.5
        if any(step.file_to_modify for step in self.steps):
            base_time += 5
        return int(base_time)

    def add_step(self, step: FixStep) -> None:
        step.order = len(self.steps)
        self.steps.append(step)
        self.touch()


class FixRecommendation(BaseModel):
    fix: FixRecord
    confidence_score: float = Field(ge=0.0, le=1.0)
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    recency_score: float = Field(default=0.0, ge=0.0, le=1.0)
    effort_score: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str
    matched_failure_id: Optional[UUID] = None
    alternative_fixes: List[UUID] = Field(default_factory=list)
    requires_manual_review: bool = Field(default=False)
    warnings: List[str] = Field(default_factory=list)

    @computed_field
    @property
    def overall_score(self) -> float:
        return (
            0.3 * self.similarity_score +
            0.3 * self.fix.effectiveness.success_rate +
            0.2 * self.recency_score +
            0.2 * self.effort_score
        )


class FixApplication(BaseDTO):
    fix_id: UUID
    failure_id: UUID
    build_id: UUID
    applied_by: str
    applied_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    success: bool = Field(default=False)
    duration_seconds: float = Field(default=0.0)
    step_results: Dict[int, bool] = Field(default_factory=dict)
    error_message: Optional[str] = None
    output_log: Optional[str] = None
    user_feedback: Optional[str] = None
    feedback_rating: Optional[int] = Field(default=None, ge=1, le=5)


class FixSearchQuery(BaseModel):
    failure_signature_hash: Optional[str] = None
    failure_category: Optional[str] = None
    rocm_version: Optional[str] = None
    gpu_architecture: Optional[str] = None
    fix_type: Optional[FixType] = None
    min_success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    include_deprecated: bool = Field(default=False)
    limit: int = Field(default=10, ge=1, le=100)


class FixStatistics(BaseModel):
    total_fixes: int = Field(default=0)
    by_type: Dict[str, int] = Field(default_factory=dict)
    by_category: Dict[str, int] = Field(default_factory=dict)
    average_success_rate: float = Field(default=0.0)
    most_effective_fixes: List[FixRecord] = Field(default_factory=list)
    most_applied_fixes: List[FixRecord] = Field(default_factory=list)
    recently_added_fixes: List[FixRecord] = Field(default_factory=list)
