from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import re
import operator

from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    name: str
    description: str
    expression: str
    severity: AlertSeverity
    for_duration: timedelta = field(default_factory=lambda: timedelta(minutes=0))
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class EvaluationResult:
    triggered: bool
    value: Optional[float] = None
    message: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AlertEvaluator:
    OPERATORS = {
        ">": operator.gt,
        "<": operator.lt,
        ">=": operator.ge,
        "<=": operator.le,
        "==": operator.eq,
        "!=": operator.ne,
    }
    
    EXPRESSION_PATTERN = re.compile(r"(\w+)\s*(>|<|>=|<=|==|!=)\s*([\d.]+)")
    
    def __init__(self):
        self._pending_alerts: Dict[str, datetime] = {}
    
    def evaluate(self, rule: AlertRule, metrics: Dict[str, float]) -> EvaluationResult:
        if not rule.enabled:
            return EvaluationResult(triggered=False)
        
        try:
            match = self.EXPRESSION_PATTERN.match(rule.expression)
            if not match:
                logger.warning(f"Invalid expression format: {rule.expression}")
                return EvaluationResult(triggered=False)
            
            metric_name, op_str, threshold_str = match.groups()
            threshold = float(threshold_str)
            
            if metric_name not in metrics:
                return EvaluationResult(triggered=False, message=f"Metric {metric_name} not found")
            
            value = metrics[metric_name]
            op_func = self.OPERATORS.get(op_str)
            
            if op_func is None:
                logger.warning(f"Unknown operator: {op_str}")
                return EvaluationResult(triggered=False)
            
            condition_met = op_func(value, threshold)
            
            if condition_met:
                if rule.for_duration.total_seconds() > 0:
                    if rule.name not in self._pending_alerts:
                        self._pending_alerts[rule.name] = datetime.now(timezone.utc)
                        return EvaluationResult(triggered=False, value=value)
                    
                    pending_since = self._pending_alerts[rule.name]
                    elapsed = datetime.now(timezone.utc) - pending_since
                    
                    if elapsed >= rule.for_duration:
                        return EvaluationResult(
                            triggered=True,
                            value=value,
                            message=f"{rule.description}: {metric_name}={value} {op_str} {threshold}",
                        )
                    return EvaluationResult(triggered=False, value=value)
                
                return EvaluationResult(
                    triggered=True,
                    value=value,
                    message=f"{rule.description}: {metric_name}={value} {op_str} {threshold}",
                )
            
            if rule.name in self._pending_alerts:
                del self._pending_alerts[rule.name]
            
            return EvaluationResult(triggered=False, value=value)
            
        except Exception as e:
            logger.error(f"Failed to evaluate rule {rule.name}: {e}")
            return EvaluationResult(triggered=False, message=str(e))
    
    def evaluate_all(self, rules: List[AlertRule], metrics: Dict[str, float]) -> Dict[str, EvaluationResult]:
        results = {}
        for rule in rules:
            results[rule.name] = self.evaluate(rule, metrics)
        return results


def create_threshold_rule(
    name: str,
    metric: str,
    threshold: float,
    operator: str = ">",
    severity: AlertSeverity = AlertSeverity.WARNING,
    description: Optional[str] = None,
) -> AlertRule:
    return AlertRule(
        name=name,
        description=description or f"{metric} {operator} {threshold}",
        expression=f"{metric} {operator} {threshold}",
        severity=severity,
    )


BUILD_FAILURE_RATE_WARNING = AlertRule(
    name="build_failure_rate_warning",
    description="Build failure rate exceeds 30%",
    expression="failure_rate > 0.3",
    severity=AlertSeverity.WARNING,
    for_duration=timedelta(minutes=5),
)

BUILD_FAILURE_RATE_CRITICAL = AlertRule(
    name="build_failure_rate_critical",
    description="Build failure rate exceeds 50%",
    expression="failure_rate > 0.5",
    severity=AlertSeverity.CRITICAL,
    for_duration=timedelta(minutes=2),
)

QUEUE_DEPTH_WARNING = AlertRule(
    name="queue_depth_warning",
    description="Build queue depth exceeds threshold",
    expression="queue_depth > 20",
    severity=AlertSeverity.WARNING,
    for_duration=timedelta(minutes=10),
)

GPU_MEMORY_WARNING = AlertRule(
    name="gpu_memory_warning",
    description="GPU memory usage exceeds 90%",
    expression="gpu_memory_percent > 90",
    severity=AlertSeverity.WARNING,
)

DEFAULT_RULES = [
    BUILD_FAILURE_RATE_WARNING,
    BUILD_FAILURE_RATE_CRITICAL,
    QUEUE_DEPTH_WARNING,
    GPU_MEMORY_WARNING,
]
