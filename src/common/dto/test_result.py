from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from src.common.dto.base import BaseDTO, TimestampMixin
from src.common.config.constants import TestStatus


class TestCase(BaseModel):
    name: str
    class_name: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    status: TestStatus
    duration_seconds: float = Field(default=0.0)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    stack_trace: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    retry_count: int = Field(default=0)
    is_flaky: bool = Field(default=False)
    skip_reason: Optional[str] = None
    gpu_required: bool = Field(default=False)
    gpu_id: Optional[int] = None
    memory_used_mb: Optional[float] = None
    gpu_memory_used_mb: Optional[float] = None
    properties: Dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def full_name(self) -> str:
        if self.class_name:
            return f"{self.class_name}::{self.name}"
        return self.name

    @computed_field
    @property
    def is_passed(self) -> bool:
        return self.status == TestStatus.PASSED

    @computed_field
    @property
    def is_failed(self) -> bool:
        return self.status == TestStatus.FAILED

    @computed_field
    @property
    def has_error(self) -> bool:
        return self.status == TestStatus.ERROR or self.error_message is not None


class TestSuite(BaseModel):
    name: str
    file_path: Optional[str] = None
    test_cases: List[TestCase] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    setup_duration_seconds: float = Field(default=0.0)
    teardown_duration_seconds: float = Field(default=0.0)
    properties: Dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def total_tests(self) -> int:
        return len(self.test_cases)

    @computed_field
    @property
    def passed_count(self) -> int:
        return sum(1 for tc in self.test_cases if tc.status == TestStatus.PASSED)

    @computed_field
    @property
    def failed_count(self) -> int:
        return sum(1 for tc in self.test_cases if tc.status == TestStatus.FAILED)

    @computed_field
    @property
    def skipped_count(self) -> int:
        return sum(1 for tc in self.test_cases if tc.status == TestStatus.SKIPPED)

    @computed_field
    @property
    def error_count(self) -> int:
        return sum(1 for tc in self.test_cases if tc.status == TestStatus.ERROR)

    @computed_field
    @property
    def total_duration_seconds(self) -> float:
        return (
            sum(tc.duration_seconds for tc in self.test_cases) +
            self.setup_duration_seconds +
            self.teardown_duration_seconds
        )

    @computed_field
    @property
    def pass_rate(self) -> float:
        if self.total_tests == 0:
            return 0.0
        return self.passed_count / self.total_tests

    def get_failed_tests(self) -> List[TestCase]:
        return [tc for tc in self.test_cases if tc.status == TestStatus.FAILED]

    def get_slow_tests(self, threshold_seconds: float = 10.0) -> List[TestCase]:
        return [
            tc for tc in self.test_cases 
            if tc.duration_seconds > threshold_seconds
        ]


class TestMetrics(BaseModel):
    total_tests: int = Field(default=0)
    passed: int = Field(default=0)
    failed: int = Field(default=0)
    skipped: int = Field(default=0)
    errors: int = Field(default=0)
    xfail: int = Field(default=0)
    xpass: int = Field(default=0)
    total_duration_seconds: float = Field(default=0.0)
    average_test_duration_seconds: float = Field(default=0.0)
    slowest_test_duration_seconds: float = Field(default=0.0)
    slowest_test_name: Optional[str] = None
    flaky_test_count: int = Field(default=0)
    gpu_test_count: int = Field(default=0)
    cpu_only_test_count: int = Field(default=0)
    peak_memory_mb: float = Field(default=0.0)
    peak_gpu_memory_mb: float = Field(default=0.0)

    @computed_field
    @property
    def pass_rate(self) -> float:
        if self.total_tests == 0:
            return 0.0
        return self.passed / self.total_tests

    @computed_field
    @property
    def failure_rate(self) -> float:
        if self.total_tests == 0:
            return 0.0
        return (self.failed + self.errors) / self.total_tests


class TestReport(BaseDTO):
    build_id: UUID
    test_suites: List[TestSuite] = Field(default_factory=list)
    metrics: TestMetrics = Field(default_factory=TestMetrics)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    report_format: str = Field(default="junit")
    report_file_path: Optional[str] = None
    rocm_version: str
    gpu_architecture: str
    python_version: str
    environment_snapshot_id: Optional[UUID] = None
    coverage_percent: Optional[float] = None
    coverage_report_path: Optional[str] = None

    def calculate_metrics(self) -> None:
        self.metrics = TestMetrics()
        all_tests: List[TestCase] = []
        
        for suite in self.test_suites:
            all_tests.extend(suite.test_cases)
        
        self.metrics.total_tests = len(all_tests)
        self.metrics.passed = sum(1 for t in all_tests if t.status == TestStatus.PASSED)
        self.metrics.failed = sum(1 for t in all_tests if t.status == TestStatus.FAILED)
        self.metrics.skipped = sum(1 for t in all_tests if t.status == TestStatus.SKIPPED)
        self.metrics.errors = sum(1 for t in all_tests if t.status == TestStatus.ERROR)
        self.metrics.xfail = sum(1 for t in all_tests if t.status == TestStatus.XFAIL)
        self.metrics.xpass = sum(1 for t in all_tests if t.status == TestStatus.XPASS)
        
        self.metrics.total_duration_seconds = sum(t.duration_seconds for t in all_tests)
        
        if all_tests:
            self.metrics.average_test_duration_seconds = (
                self.metrics.total_duration_seconds / len(all_tests)
            )
            slowest = max(all_tests, key=lambda t: t.duration_seconds)
            self.metrics.slowest_test_duration_seconds = slowest.duration_seconds
            self.metrics.slowest_test_name = slowest.full_name
        
        self.metrics.flaky_test_count = sum(1 for t in all_tests if t.is_flaky)
        self.metrics.gpu_test_count = sum(1 for t in all_tests if t.gpu_required)
        self.metrics.cpu_only_test_count = sum(1 for t in all_tests if not t.gpu_required)
        
        memory_values = [t.memory_used_mb for t in all_tests if t.memory_used_mb]
        if memory_values:
            self.metrics.peak_memory_mb = max(memory_values)
        
        gpu_memory_values = [t.gpu_memory_used_mb for t in all_tests if t.gpu_memory_used_mb]
        if gpu_memory_values:
            self.metrics.peak_gpu_memory_mb = max(gpu_memory_values)

    def get_all_failures(self) -> List[TestCase]:
        failures = []
        for suite in self.test_suites:
            failures.extend(suite.get_failed_tests())
        return failures

    def get_failure_summary(self) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for failure in self.get_all_failures():
            error_type = failure.error_type or "Unknown"
            summary[error_type] = summary.get(error_type, 0) + 1
        return summary


class TestComparison(BaseModel):
    baseline_report_id: UUID
    current_report_id: UUID
    new_failures: List[str] = Field(default_factory=list)
    fixed_tests: List[str] = Field(default_factory=list)
    new_tests: List[str] = Field(default_factory=list)
    removed_tests: List[str] = Field(default_factory=list)
    duration_change_percent: float = Field(default=0.0)
    pass_rate_change: float = Field(default=0.0)
    flaky_tests: List[str] = Field(default_factory=list)

    @computed_field
    @property
    def has_regressions(self) -> bool:
        return len(self.new_failures) > 0


class FlakyTestRecord(BaseModel):
    test_name: str
    test_class: Optional[str] = None
    file_path: Optional[str] = None
    total_runs: int = Field(default=0)
    pass_count: int = Field(default=0)
    fail_count: int = Field(default=0)
    first_seen: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_seen: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    is_quarantined: bool = Field(default=False)
    quarantine_reason: Optional[str] = None

    @computed_field
    @property
    def flakiness_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        minority = min(self.pass_count, self.fail_count)
        return minority / self.total_runs
