from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class BuildResponse(BaseModel):
    build_id: str
    repository: str
    branch: str
    commit_sha: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)
    artifacts: List[Dict[str, str]] = Field(default_factory=list)
    logs_url: Optional[str] = None


class BuildListResponse(BaseModel):
    items: List[BuildResponse]
    total: int
    limit: int
    offset: int


class FailureResponse(BaseModel):
    failure_id: str
    build_id: Optional[str] = None
    category: str
    error_message: Optional[str] = None
    signature: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    created_at: Optional[datetime] = None


class FailureDetailResponse(FailureResponse):
    root_cause: Optional[str] = None
    recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    similar_failures: List[str] = Field(default_factory=list)


class FixResponse(BaseModel):
    recommendation_id: str
    type: str
    title: str
    description: str
    priority: int
    steps: List[str] = Field(default_factory=list)
    confidence: float
    auto_applicable: bool
    estimated_time_minutes: int


class FixListResponse(BaseModel):
    items: List[FixResponse]
    total: int


class MetricsResponse(BaseModel):
    period_days: int
    total_builds: int
    success_rate: float
    average_duration_seconds: float
    status_distribution: Dict[str, int] = Field(default_factory=dict)


class TrendResponse(BaseModel):
    data_points: List[Dict[str, Any]]
    metric: str
    granularity: str
    start_date: datetime
    end_date: datetime


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    version: str
    components: List[Dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
