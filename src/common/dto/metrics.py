from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from src.common.dto.base import BaseDTO, TimestampMixin
from src.common.config.constants import BuildStatus


class GPUMetrics(BaseModel):
    device_id: int
    architecture: str
    utilization_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    memory_used_mb: float = Field(default=0.0)
    memory_total_mb: float = Field(default=0.0)
    temperature_celsius: float = Field(default=0.0)
    power_usage_watts: float = Field(default=0.0)
    power_limit_watts: float = Field(default=0.0)
    clock_speed_mhz: float = Field(default=0.0)
    memory_clock_mhz: float = Field(default=0.0)
    fan_speed_percent: Optional[float] = None
    pcie_throughput_mbps: Optional[float] = None
    ecc_errors: int = Field(default=0)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @computed_field
    @property
    def memory_utilization_percent(self) -> float:
        if self.memory_total_mb == 0:
            return 0.0
        return (self.memory_used_mb / self.memory_total_mb) * 100

    @computed_field
    @property
    def power_utilization_percent(self) -> float:
        if self.power_limit_watts == 0:
            return 0.0
        return (self.power_usage_watts / self.power_limit_watts) * 100

    @computed_field
    @property
    def is_thermal_throttling(self) -> bool:
        return self.temperature_celsius > 85.0


class ResourceMetrics(BaseModel):
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    cpu_utilization_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    cpu_cores_used: float = Field(default=0.0)
    cpu_cores_total: int = Field(default=0)
    memory_used_mb: float = Field(default=0.0)
    memory_total_mb: float = Field(default=0.0)
    memory_cached_mb: float = Field(default=0.0)
    swap_used_mb: float = Field(default=0.0)
    swap_total_mb: float = Field(default=0.0)
    disk_read_mbps: float = Field(default=0.0)
    disk_write_mbps: float = Field(default=0.0)
    disk_iops_read: float = Field(default=0.0)
    disk_iops_write: float = Field(default=0.0)
    network_rx_mbps: float = Field(default=0.0)
    network_tx_mbps: float = Field(default=0.0)
    gpu_metrics: List[GPUMetrics] = Field(default_factory=list)

    @computed_field
    @property
    def memory_utilization_percent(self) -> float:
        if self.memory_total_mb == 0:
            return 0.0
        return (self.memory_used_mb / self.memory_total_mb) * 100

    @computed_field
    @property
    def total_gpu_memory_used_mb(self) -> float:
        return sum(g.memory_used_mb for g in self.gpu_metrics)

    @computed_field
    @property
    def average_gpu_utilization(self) -> float:
        if not self.gpu_metrics:
            return 0.0
        return sum(g.utilization_percent for g in self.gpu_metrics) / len(self.gpu_metrics)


class BuildMetricsData(BaseModel):
    build_id: UUID
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: BuildStatus
    total_duration_seconds: float = Field(default=0.0)
    queue_wait_seconds: float = Field(default=0.0)
    checkout_duration_seconds: float = Field(default=0.0)
    dependency_install_seconds: float = Field(default=0.0)
    cmake_configure_seconds: float = Field(default=0.0)
    compilation_seconds: float = Field(default=0.0)
    test_execution_seconds: float = Field(default=0.0)
    artifact_upload_seconds: float = Field(default=0.0)
    cleanup_seconds: float = Field(default=0.0)
    
    compilation_units_total: int = Field(default=0)
    compilation_units_cached: int = Field(default=0)
    compilation_warnings: int = Field(default=0)
    compilation_errors: int = Field(default=0)
    
    tests_total: int = Field(default=0)
    tests_passed: int = Field(default=0)
    tests_failed: int = Field(default=0)
    tests_skipped: int = Field(default=0)
    
    peak_memory_mb: float = Field(default=0.0)
    peak_gpu_memory_mb: float = Field(default=0.0)
    average_cpu_utilization: float = Field(default=0.0)
    average_gpu_utilization: float = Field(default=0.0)
    
    artifacts_size_mb: float = Field(default=0.0)
    log_size_mb: float = Field(default=0.0)

    @computed_field
    @property
    def cache_hit_rate(self) -> float:
        if self.compilation_units_total == 0:
            return 0.0
        return self.compilation_units_cached / self.compilation_units_total

    @computed_field
    @property
    def test_pass_rate(self) -> float:
        if self.tests_total == 0:
            return 0.0
        return self.tests_passed / self.tests_total


class PerformanceMetrics(BaseModel):
    period_start: datetime
    period_end: datetime
    total_builds: int = Field(default=0)
    successful_builds: int = Field(default=0)
    failed_builds: int = Field(default=0)
    cancelled_builds: int = Field(default=0)
    timeout_builds: int = Field(default=0)
    
    average_build_duration_seconds: float = Field(default=0.0)
    p50_build_duration_seconds: float = Field(default=0.0)
    p90_build_duration_seconds: float = Field(default=0.0)
    p99_build_duration_seconds: float = Field(default=0.0)
    
    average_queue_wait_seconds: float = Field(default=0.0)
    max_queue_wait_seconds: float = Field(default=0.0)
    
    average_test_pass_rate: float = Field(default=0.0)
    flaky_test_count: int = Field(default=0)
    
    average_cache_hit_rate: float = Field(default=0.0)
    
    total_gpu_hours: float = Field(default=0.0)
    average_gpu_utilization: float = Field(default=0.0)
    
    most_common_failure_categories: Dict[str, int] = Field(default_factory=dict)
    failure_resolution_rate: float = Field(default=0.0)

    @computed_field
    @property
    def success_rate(self) -> float:
        if self.total_builds == 0:
            return 0.0
        return self.successful_builds / self.total_builds

    @computed_field
    @property
    def period_duration_hours(self) -> float:
        return (self.period_end - self.period_start).total_seconds() / 3600


class AggregatedMetrics(BaseDTO):
    aggregation_type: str = Field(default="daily")
    period_start: datetime
    period_end: datetime
    
    builds_by_status: Dict[str, int] = Field(default_factory=dict)
    builds_by_rocm_version: Dict[str, int] = Field(default_factory=dict)
    builds_by_gpu_architecture: Dict[str, int] = Field(default_factory=dict)
    builds_by_hour: Dict[int, int] = Field(default_factory=dict)
    builds_by_day_of_week: Dict[int, int] = Field(default_factory=dict)
    
    performance: PerformanceMetrics
    
    top_failure_patterns: List[Dict[str, Any]] = Field(default_factory=list)
    top_flaky_tests: List[Dict[str, Any]] = Field(default_factory=list)
    slowest_builds: List[Dict[str, Any]] = Field(default_factory=list)
    
    resource_utilization_trend: List[ResourceMetrics] = Field(default_factory=list)
    
    comparison_to_previous_period: Optional[Dict[str, float]] = None


class DashboardMetrics(BaseModel):
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    current_queue_depth: int = Field(default=0)
    running_builds: int = Field(default=0)
    available_gpu_slots: int = Field(default=0)
    estimated_queue_wait_minutes: float = Field(default=0.0)
    
    last_24h_success_rate: float = Field(default=0.0)
    last_24h_builds: int = Field(default=0)
    last_24h_failures: int = Field(default=0)
    
    last_7d_trend: List[Dict[str, Any]] = Field(default_factory=list)
    
    active_alerts: List[Dict[str, Any]] = Field(default_factory=list)
    
    system_health: Dict[str, str] = Field(default_factory=dict)
    
    recent_builds: List[Dict[str, Any]] = Field(default_factory=list)


class AlertMetric(BaseModel):
    alert_id: str
    alert_name: str
    severity: str
    condition: str
    current_value: float
    threshold_value: float
    triggered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    notification_sent: bool = Field(default=False)
    affected_resources: List[str] = Field(default_factory=list)

    @computed_field
    @property
    def is_active(self) -> bool:
        return self.resolved_at is None

    @computed_field
    @property
    def duration_seconds(self) -> float:
        end_time = self.resolved_at or datetime.now(timezone.utc)
        return (end_time - self.triggered_at).total_seconds()
