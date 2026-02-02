from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
import asyncio

from src.monitoring.alerting.alert_rules import AlertRule, AlertEvaluator
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertState(str, Enum):
    PENDING = "pending"
    FIRING = "firing"
    RESOLVED = "resolved"


@dataclass
class Alert:
    alert_id: str
    name: str
    severity: AlertSeverity
    message: str
    state: AlertState = AlertState.PENDING
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    fired_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    value: Optional[float] = None
    
    def fire(self) -> None:
        self.state = AlertState.FIRING
        self.fired_at = datetime.now(timezone.utc)
    
    def resolve(self) -> None:
        self.state = AlertState.RESOLVED
        self.resolved_at = datetime.now(timezone.utc)


class AlertManager:
    def __init__(self):
        self._rules: List[AlertRule] = []
        self._evaluator = AlertEvaluator()
        self._active_alerts: Dict[str, Alert] = {}
        self._alert_history: List[Alert] = []
        self._notification_handlers: List[Callable[[Alert], Any]] = []
        self._evaluation_interval = 60
        self._running = False
    
    def add_rule(self, rule: AlertRule) -> None:
        self._rules.append(rule)
        logger.info(f"Alert rule added: {rule.name}")
    
    def remove_rule(self, rule_name: str) -> bool:
        for i, rule in enumerate(self._rules):
            if rule.name == rule_name:
                self._rules.pop(i)
                logger.info(f"Alert rule removed: {rule_name}")
                return True
        return False
    
    def register_notification_handler(self, handler: Callable[[Alert], Any]) -> None:
        self._notification_handlers.append(handler)
    
    async def evaluate_rules(self, metrics: Dict[str, float]) -> List[Alert]:
        triggered_alerts = []
        
        for rule in self._rules:
            try:
                result = self._evaluator.evaluate(rule, metrics)
                
                if result.triggered:
                    alert = Alert(
                        alert_id=f"{rule.name}_{datetime.now(timezone.utc).timestamp()}",
                        name=rule.name,
                        severity=rule.severity,
                        message=result.message or rule.description,
                        labels=rule.labels.copy(),
                        value=result.value,
                    )
                    alert.fire()
                    
                    self._active_alerts[rule.name] = alert
                    triggered_alerts.append(alert)
                    
                    logger.warning(f"Alert triggered: {rule.name} - {alert.message}")
                    
                    for handler in self._notification_handlers:
                        try:
                            if asyncio.iscoroutinefunction(handler):
                                await handler(alert)
                            else:
                                handler(alert)
                        except Exception as e:
                            logger.error(f"Notification handler failed: {e}")
                
                elif rule.name in self._active_alerts:
                    alert = self._active_alerts.pop(rule.name)
                    alert.resolve()
                    self._alert_history.append(alert)
                    logger.info(f"Alert resolved: {rule.name}")
                    
            except Exception as e:
                logger.error(f"Failed to evaluate rule {rule.name}: {e}")
        
        return triggered_alerts
    
    async def start_evaluation_loop(self, metrics_provider: Callable[[], Dict[str, float]]) -> None:
        self._running = True
        logger.info("Alert evaluation loop started")
        
        while self._running:
            try:
                metrics = metrics_provider()
                await self.evaluate_rules(metrics)
            except Exception as e:
                logger.error(f"Evaluation loop error: {e}")
            
            await asyncio.sleep(self._evaluation_interval)
    
    def stop_evaluation_loop(self) -> None:
        self._running = False
        logger.info("Alert evaluation loop stopped")
    
    def get_active_alerts(self) -> List[Alert]:
        return list(self._active_alerts.values())
    
    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        return self._alert_history[-limit:]
    
    def acknowledge_alert(self, alert_name: str) -> bool:
        if alert_name in self._active_alerts:
            alert = self._active_alerts[alert_name]
            alert.annotations["acknowledged"] = "true"
            alert.annotations["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
            return True
        return False
    
    def register_default_rules(self) -> None:
        self.add_rule(AlertRule(
            name="high_failure_rate",
            description="Build failure rate exceeds threshold",
            expression="failure_rate > 0.3",
            severity=AlertSeverity.WARNING,
            for_duration=timedelta(minutes=5),
            labels={"team": "ci"},
        ))
        
        self.add_rule(AlertRule(
            name="critical_failure_rate",
            description="Build failure rate is critically high",
            expression="failure_rate > 0.5",
            severity=AlertSeverity.CRITICAL,
            for_duration=timedelta(minutes=2),
            labels={"team": "ci", "priority": "high"},
        ))
        
        self.add_rule(AlertRule(
            name="long_queue_wait",
            description="Build queue wait time exceeds threshold",
            expression="queue_wait_seconds > 1800",
            severity=AlertSeverity.WARNING,
            for_duration=timedelta(minutes=10),
            labels={"team": "infra"},
        ))
        
        self.add_rule(AlertRule(
            name="gpu_unhealthy",
            description="GPU health check failed",
            expression="gpu_healthy == 0",
            severity=AlertSeverity.CRITICAL,
            for_duration=timedelta(minutes=1),
            labels={"team": "infra", "component": "gpu"},
        ))
        
        logger.info("Default alert rules registered")
