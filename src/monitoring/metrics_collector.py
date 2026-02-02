from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
import asyncio
import time

from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class MetricValue:
    name: str
    value: float
    metric_type: MetricType
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HistogramBucket:
    le: float
    count: int


class Histogram:
    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    
    def __init__(self, name: str, buckets: Optional[List[float]] = None):
        self.name = name
        self._buckets = sorted(buckets or self.DEFAULT_BUCKETS)
        self._counts: Dict[float, int] = {b: 0 for b in self._buckets}
        self._counts[float("inf")] = 0
        self._sum = 0.0
        self._count = 0
    
    def observe(self, value: float) -> None:
        self._sum += value
        self._count += 1
        for bucket in self._buckets:
            if value <= bucket:
                self._counts[bucket] += 1
        self._counts[float("inf")] += 1
    
    def get_buckets(self) -> List[HistogramBucket]:
        return [HistogramBucket(le=b, count=c) for b, c in self._counts.items()]
    
    @property
    def sum(self) -> float:
        return self._sum
    
    @property
    def count(self) -> int:
        return self._count


class MetricsCollector:
    def __init__(self, prefix: str = "cicd"):
        self._prefix = prefix
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._labels: Dict[str, Dict[str, str]] = {}
        self._lock = asyncio.Lock()
    
    def _make_key(self, name: str, labels: Optional[Dict[str, str]] = None) -> str:
        key = f"{self._prefix}_{name}"
        if labels:
            label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            key = f"{key}{{{label_str}}}"
        return key
    
    async def increment_counter(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        key = self._make_key(name, labels)
        async with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value
            if labels:
                self._labels[key] = labels
    
    async def set_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        key = self._make_key(name, labels)
        async with self._lock:
            self._gauges[key] = value
            if labels:
                self._labels[key] = labels
    
    async def observe_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        buckets: Optional[List[float]] = None,
    ) -> None:
        key = self._make_key(name, labels)
        async with self._lock:
            if key not in self._histograms:
                self._histograms[key] = Histogram(name, buckets)
            self._histograms[key].observe(value)
            if labels:
                self._labels[key] = labels
    
    def timer(self, name: str, labels: Optional[Dict[str, str]] = None):
        return MetricTimer(self, name, labels)
    
    async def get_all_metrics(self) -> List[MetricValue]:
        metrics = []
        
        async with self._lock:
            for key, value in self._counters.items():
                name = key.split("{")[0]
                labels = self._labels.get(key, {})
                metrics.append(MetricValue(
                    name=name,
                    value=value,
                    metric_type=MetricType.COUNTER,
                    labels=labels,
                ))
            
            for key, value in self._gauges.items():
                name = key.split("{")[0]
                labels = self._labels.get(key, {})
                metrics.append(MetricValue(
                    name=name,
                    value=value,
                    metric_type=MetricType.GAUGE,
                    labels=labels,
                ))
            
            for key, histogram in self._histograms.items():
                name = key.split("{")[0]
                labels = self._labels.get(key, {})
                metrics.append(MetricValue(
                    name=f"{name}_count",
                    value=histogram.count,
                    metric_type=MetricType.HISTOGRAM,
                    labels=labels,
                ))
                metrics.append(MetricValue(
                    name=f"{name}_sum",
                    value=histogram.sum,
                    metric_type=MetricType.HISTOGRAM,
                    labels=labels,
                ))
        
        return metrics
    
    async def export_prometheus(self) -> str:
        lines = []
        metrics = await self.get_all_metrics()
        
        for metric in metrics:
            labels_str = ""
            if metric.labels:
                pairs = ",".join(f'{k}="{v}"' for k, v in metric.labels.items())
                labels_str = f"{{{pairs}}}"
            lines.append(f"{metric.name}{labels_str} {metric.value}")
        
        return "\n".join(lines)
    
    async def record_build_started(self, repository: str, branch: str) -> None:
        await self.increment_counter("builds_started_total", labels={
            "repository": repository,
            "branch": branch,
        })
        await self.set_gauge("builds_in_progress", 1, labels={"repository": repository})
    
    async def record_build_completed(
        self,
        repository: str,
        branch: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        await self.increment_counter("builds_completed_total", labels={
            "repository": repository,
            "branch": branch,
            "status": status,
        })
        await self.observe_histogram("build_duration_seconds", duration_seconds, labels={
            "repository": repository,
        })
        await self.set_gauge("builds_in_progress", 0, labels={"repository": repository})


class MetricTimer:
    def __init__(
        self,
        collector: MetricsCollector,
        name: str,
        labels: Optional[Dict[str, str]] = None,
    ):
        self._collector = collector
        self._name = name
        self._labels = labels
        self._start_time: Optional[float] = None
    
    async def __aenter__(self):
        self._start_time = time.perf_counter()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._start_time:
            duration = time.perf_counter() - self._start_time
            await self._collector.observe_histogram(self._name, duration, self._labels)
