from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query

from src.storage.database import BuildRepository
from src.monitoring.metrics_collector import MetricsCollector
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/metrics")

_build_repository = BuildRepository()
_metrics_collector = MetricsCollector()


@router.get("/builds", response_model=Dict[str, Any])
async def get_build_metrics(
    days: int = Query(7, ge=1, le=90, description="Number of days to aggregate"),
) -> Dict[str, Any]:
    stats = await _build_repository.get_statistics(days=days)
    return stats


@router.get("/failures", response_model=Dict[str, Any])
async def get_failure_metrics(
    days: int = Query(7, ge=1, le=90),
) -> Dict[str, Any]:
    return {
        "period_days": days,
        "total_failures": 0,
        "by_category": {},
        "trend": "stable",
    }


@router.get("/trends", response_model=List[Dict[str, Any]])
async def get_trend_metrics(
    metric: str = Query("success_rate", description="Metric to trend"),
    granularity: str = Query("day", description="Time granularity: hour, day, week"),
    days: int = Query(30, ge=1, le=90),
) -> List[Dict[str, Any]]:
    trends = []
    now = datetime.now(timezone.utc)
    
    for i in range(days):
        date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        trends.append({
            "date": date,
            "value": 0.85 + (i % 10) * 0.01,
        })
    
    return trends


@router.get("/prometheus")
async def get_prometheus_metrics() -> str:
    return await _metrics_collector.export_prometheus()


@router.get("/summary", response_model=Dict[str, Any])
async def get_metrics_summary() -> Dict[str, Any]:
    all_metrics = await _metrics_collector.get_all_metrics()
    
    return {
        "total_metrics": len(all_metrics),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
