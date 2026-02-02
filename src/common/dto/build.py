from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from src.common.dto.base import BaseDTO, TimestampMixin
from src.common.config.constants import (
    BuildStatus,
    Priority,
    ROCmVersion,
    GPUArchitecture,
    BuildType,
)


class BuildConfiguration(BaseModel):
    rocm_version: str = Field(description="ROCm version to use")
    gpu_architecture: str = Field(description="Target GPU architecture")
    build_type: BuildType = Field(default=BuildType.RELEASE)
    python_version: str = Field(default="3.10")
    cmake_flags: List[str] = Field(default_factory=list)
    environment_variables: Dict[str, str] = Field(default_factory=dict)
    compiler: str = Field(default="hipcc")
    enable_tests: bool = Field(default=True)
    enable_benchmarks: bool = Field(default=False)
    parallel_jobs: int = Field(default=8, ge=1, le=64)
    use_ccache: bool = Field(default=True)
    debug_symbols: bool = Field(default=False)

    @field_validator("rocm_version")
    @classmethod
    def validate_rocm_version(cls, v: str) -> str:
        parts = v.split(".")
        if len(parts) < 2:
            raise ValueError(f"Invalid ROCm version format: {v}")
        return v

    @field_validator("python_version")
    @classmethod
    def validate_python_version(cls, v: str) -> str:
        supported = ["3.8", "3.9", "3.10", "3.11", "3.12"]
        if v not in supported:
            raise ValueError(f"Unsupported Python version: {v}")
        return v


class BuildEnvironment(BaseModel):
    node_name: Optional[str] = None
    pod_name: Optional[str] = None
    namespace: str = Field(default="default")
    gpu_device_ids: List[int] = Field(default_factory=list)
    cpu_cores_allocated: int = Field(default=8)
    memory_gb_allocated: float = Field(default=32.0)
    work_directory: str = Field(default="/workspace")
    cache_directory: str = Field(default="/cache")
    artifact_directory: str = Field(default="/artifacts")
    docker_image: Optional[str] = None


class BuildRequest(BaseDTO):
    repository: str = Field(description="Repository URL or name")
    branch: str = Field(default="main")
    commit_sha: str = Field(description="Git commit SHA to build")
    pr_number: Optional[int] = None
    pr_title: Optional[str] = None
    pr_author: Optional[str] = None
    configurations: List[BuildConfiguration] = Field(default_factory=list)
    priority: Priority = Field(default=Priority.NORMAL)
    triggered_by: str = Field(default="webhook")
    callback_url: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    skip_tests: bool = Field(default=False)
    skip_cache: bool = Field(default=False)

    @field_validator("commit_sha")
    @classmethod
    def validate_commit_sha(cls, v: str) -> str:
        if len(v) < 7:
            raise ValueError("Commit SHA must be at least 7 characters")
        if not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("Invalid commit SHA format")
        return v.lower()


class BuildArtifact(BaseModel):
    name: str
    path: str
    size_bytes: int = Field(default=0)
    checksum_sha256: Optional[str] = None
    artifact_type: str = Field(default="binary")
    retention_days: int = Field(default=90)
    download_url: Optional[str] = None
    upload_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class BuildMetrics(BaseModel):
    total_duration_seconds: float = Field(default=0.0)
    configuration_duration_seconds: float = Field(default=0.0)
    compilation_duration_seconds: float = Field(default=0.0)
    test_duration_seconds: float = Field(default=0.0)
    artifact_upload_duration_seconds: float = Field(default=0.0)
    peak_memory_mb: float = Field(default=0.0)
    peak_gpu_memory_mb: float = Field(default=0.0)
    cpu_time_seconds: float = Field(default=0.0)
    gpu_utilization_percent: float = Field(default=0.0)
    cache_hit_rate: float = Field(default=0.0)
    compilation_units: int = Field(default=0)
    compilation_errors: int = Field(default=0)
    compilation_warnings: int = Field(default=0)
    test_cases_total: int = Field(default=0)
    test_cases_passed: int = Field(default=0)
    test_cases_failed: int = Field(default=0)
    test_cases_skipped: int = Field(default=0)


class BuildResult(BaseDTO):
    request_id: UUID
    configuration: BuildConfiguration
    environment: Optional[BuildEnvironment] = None
    status: BuildStatus = Field(default=BuildStatus.PENDING)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    metrics: BuildMetrics = Field(default_factory=BuildMetrics)
    artifacts: List[BuildArtifact] = Field(default_factory=list)
    log_url: Optional[str] = None
    error_message: Optional[str] = None
    failure_ids: List[UUID] = Field(default_factory=list)
    retry_count: int = Field(default=0)
    parent_build_id: Optional[UUID] = None

    @property
    def duration(self) -> Optional[timedelta]:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None

    @property
    def is_successful(self) -> bool:
        return self.status == BuildStatus.SUCCESS

    @property
    def is_failed(self) -> bool:
        return self.status == BuildStatus.FAILURE

    @property
    def is_running(self) -> bool:
        return self.status == BuildStatus.RUNNING

    def start(self) -> None:
        self.status = BuildStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)
        self.touch()

    def complete(self, success: bool = True) -> None:
        self.status = BuildStatus.SUCCESS if success else BuildStatus.FAILURE
        self.finished_at = datetime.now(timezone.utc)
        if self.started_at:
            self.metrics.total_duration_seconds = (
                self.finished_at - self.started_at
            ).total_seconds()
        self.touch()

    def fail(self, error_message: str) -> None:
        self.status = BuildStatus.FAILURE
        self.error_message = error_message
        self.finished_at = datetime.now(timezone.utc)
        self.touch()

    def cancel(self) -> None:
        self.status = BuildStatus.CANCELLED
        self.finished_at = datetime.now(timezone.utc)
        self.touch()


class BuildSummary(BaseModel):
    build_id: UUID
    status: BuildStatus
    repository: str
    branch: str
    commit_sha: str
    pr_number: Optional[int] = None
    rocm_version: str
    gpu_architecture: str
    duration_seconds: Optional[float] = None
    test_pass_rate: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class BuildQueue(BaseModel):
    queued_builds: List[BuildRequest] = Field(default_factory=list)
    running_builds: List[BuildResult] = Field(default_factory=list)
    total_queued: int = Field(default=0)
    total_running: int = Field(default=0)
    estimated_wait_seconds: int = Field(default=0)
    available_gpu_slots: int = Field(default=0)
