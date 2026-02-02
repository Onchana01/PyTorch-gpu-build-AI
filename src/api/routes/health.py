from fastapi import APIRouter, status
from typing import Dict, Any
from datetime import datetime, timezone

from src.monitoring.health_checker import HealthChecker, HealthStatus
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)
router = APIRouter()

_health_checker = HealthChecker()
_health_checker.register_default_checks()


@router.get("/health", response_model=Dict[str, Any])
async def health_check() -> Dict[str, Any]:
    system_health = await _health_checker.check_all()
    
    return {
        "status": system_health.status.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "components": [
            {
                "name": c.name,
                "status": c.status.value,
                "message": c.message,
                "latency_ms": c.latency_ms,
            }
            for c in system_health.components
        ],
    }


@router.get("/ready")
async def readiness_check() -> Dict[str, str]:
    system_health = await _health_checker.check_all()
    
    if system_health.status == HealthStatus.UNHEALTHY:
        return {"status": "not_ready", "reason": "System unhealthy"}
    
    return {"status": "ready"}


@router.get("/live")
async def liveness_check() -> Dict[str, str]:
    return {"status": "alive", "timestamp": datetime.now(timezone.utc).isoformat()}
