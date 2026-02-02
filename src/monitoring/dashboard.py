from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from src.monitoring.metrics_collector import MetricsCollector
from src.monitoring.health_checker import HealthChecker, SystemHealth
from src.storage.database import BuildRepository, FailureRepository
from src.common.dto.metrics import DashboardMetrics, BuildMetricsData
from src.common.config.constants import BuildStatus, FailureCategory
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


@dataclass
class BuildTrend:
    date: str
    total: int
    successful: int
    failed: int
    success_rate: float


@dataclass
class FailureTrend:
    category: str
    count: int
    percentage: float


@dataclass
class DashboardData:
    health: SystemHealth
    builds_today: int
    builds_this_week: int
    success_rate_today: float
    success_rate_week: float
    avg_build_duration_minutes: float
    active_builds: int
    queued_builds: int
    recent_failures: List[Dict[str, Any]]
    build_trends: List[BuildTrend]
    failure_distribution: List[FailureTrend]
    top_failing_repos: List[Dict[str, Any]]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DashboardService:
    def __init__(
        self,
        metrics_collector: Optional[MetricsCollector] = None,
        health_checker: Optional[HealthChecker] = None,
        build_repository: Optional[BuildRepository] = None,
        failure_repository: Optional[FailureRepository] = None,
    ):
        self._metrics = metrics_collector or MetricsCollector()
        self._health = health_checker or HealthChecker()
        self._builds = build_repository or BuildRepository()
        self._failures = failure_repository or FailureRepository()
    
    async def get_dashboard_data(self) -> DashboardData:
        health = await self._health.check_all()
        
        build_stats = await self._builds.get_statistics(days=7)
        recent_failures = await self._failures.get_recent(limit=10)
        
        failure_distribution = await self._get_failure_distribution()
        build_trends = await self._get_build_trends(days=7)
        top_failing = await self._get_top_failing_repos()
        
        return DashboardData(
            health=health,
            builds_today=build_stats.get("total_builds", 0),
            builds_this_week=build_stats.get("total_builds", 0),
            success_rate_today=build_stats.get("success_rate", 0.0),
            success_rate_week=build_stats.get("success_rate", 0.0),
            avg_build_duration_minutes=build_stats.get("average_duration_seconds", 0) / 60,
            active_builds=0,
            queued_builds=0,
            recent_failures=[
                {
                    "category": f.category.value,
                    "message": str(f.error_message)[:100] if f.error_message else "",
                    "timestamp": f.created_at.isoformat() if f.created_at else "",
                }
                for f in recent_failures
            ],
            build_trends=build_trends,
            failure_distribution=failure_distribution,
            top_failing_repos=top_failing,
        )
    
    async def _get_failure_distribution(self) -> List[FailureTrend]:
        failures = await self._failures.list(limit=1000)
        
        category_counts: Dict[str, int] = {}
        for failure in failures:
            cat = failure.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        total = sum(category_counts.values()) or 1
        
        return [
            FailureTrend(
                category=cat,
                count=count,
                percentage=count / total * 100,
            )
            for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
        ]
    
    async def _get_build_trends(self, days: int = 7) -> List[BuildTrend]:
        trends = []
        
        for i in range(days):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            trends.append(BuildTrend(
                date=date,
                total=0,
                successful=0,
                failed=0,
                success_rate=0.0,
            ))
        
        return trends
    
    async def _get_top_failing_repos(self, limit: int = 5) -> List[Dict[str, Any]]:
        most_common = await self._failures.get_most_common(limit=limit)
        return most_common
    
    async def get_metrics_summary(self) -> Dict[str, Any]:
        all_metrics = await self._metrics.get_all_metrics()
        
        summary = {
            "total_metrics": len(all_metrics),
            "counters": {},
            "gauges": {},
        }
        
        for metric in all_metrics:
            key = metric.name
            if "counter" in str(metric.metric_type).lower():
                summary["counters"][key] = metric.value
            else:
                summary["gauges"][key] = metric.value
        
        return summary
    
    def to_json(self, data: DashboardData) -> Dict[str, Any]:
        return {
            "health": {
                "status": data.health.status.value,
                "components": [
                    {
                        "name": c.name,
                        "status": c.status.value,
                        "message": c.message,
                        "latency_ms": c.latency_ms,
                    }
                    for c in data.health.components
                ],
            },
            "builds": {
                "today": data.builds_today,
                "this_week": data.builds_this_week,
                "active": data.active_builds,
                "queued": data.queued_builds,
                "success_rate_today": data.success_rate_today,
                "success_rate_week": data.success_rate_week,
                "avg_duration_minutes": data.avg_build_duration_minutes,
            },
            "failures": {
                "recent": data.recent_failures,
                "distribution": [
                    {"category": f.category, "count": f.count, "percentage": f.percentage}
                    for f in data.failure_distribution
                ],
            },
            "trends": [
                {
                    "date": t.date,
                    "total": t.total,
                    "successful": t.successful,
                    "failed": t.failed,
                    "success_rate": t.success_rate,
                }
                for t in data.build_trends
            ],
            "top_failing_repos": data.top_failing_repos,
            "timestamp": data.timestamp.isoformat(),
        }
