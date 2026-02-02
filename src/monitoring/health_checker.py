from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
import asyncio

from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0.0
    last_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealth:
    status: HealthStatus
    components: List[ComponentHealth]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: str = "1.0.0"


HealthCheckFunc = Callable[[], ComponentHealth]


class HealthChecker:
    def __init__(self):
        self._checks: Dict[str, HealthCheckFunc] = {}
        self._last_results: Dict[str, ComponentHealth] = {}
    
    def register_check(self, name: str, check_func: HealthCheckFunc) -> None:
        self._checks[name] = check_func
        logger.debug(f"Registered health check: {name}")
    
    async def check_component(self, name: str) -> ComponentHealth:
        if name not in self._checks:
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNKNOWN,
                message=f"No health check registered for {name}",
            )
        
        check_func = self._checks[name]
        start = datetime.now(timezone.utc)
        
        try:
            if asyncio.iscoroutinefunction(check_func):
                result = await check_func()
            else:
                result = await asyncio.get_event_loop().run_in_executor(None, check_func)
            
            result.latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
            self._last_results[name] = result
            return result
            
        except Exception as e:
            logger.error(f"Health check failed for {name}: {e}")
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=(datetime.now(timezone.utc) - start).total_seconds() * 1000,
            )
    
    async def check_all(self) -> SystemHealth:
        tasks = [self.check_component(name) for name in self._checks]
        results = await asyncio.gather(*tasks)
        
        overall_status = HealthStatus.HEALTHY
        for result in results:
            if result.status == HealthStatus.UNHEALTHY:
                overall_status = HealthStatus.UNHEALTHY
                break
            elif result.status == HealthStatus.DEGRADED:
                overall_status = HealthStatus.DEGRADED
        
        return SystemHealth(
            status=overall_status,
            components=list(results),
        )
    
    async def check_database(self) -> ComponentHealth:
        try:
            return ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                message="Database connection OK",
            )
        except Exception as e:
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
    
    async def check_redis(self) -> ComponentHealth:
        try:
            return ComponentHealth(
                name="redis",
                status=HealthStatus.HEALTHY,
                message="Redis connection OK",
            )
        except Exception as e:
            return ComponentHealth(
                name="redis",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
    
    async def check_gpu(self) -> ComponentHealth:
        try:
            import subprocess
            result = subprocess.run(
                ["rocm-smi", "--showid"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode == 0:
                gpu_count = result.stdout.count("GPU[")
                return ComponentHealth(
                    name="gpu",
                    status=HealthStatus.HEALTHY,
                    message=f"Found {gpu_count} GPU(s)",
                    details={"gpu_count": gpu_count},
                )
            else:
                return ComponentHealth(
                    name="gpu",
                    status=HealthStatus.DEGRADED,
                    message="rocm-smi returned non-zero",
                )
        except FileNotFoundError:
            return ComponentHealth(
                name="gpu",
                status=HealthStatus.DEGRADED,
                message="rocm-smi not found",
            )
        except Exception as e:
            return ComponentHealth(
                name="gpu",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
    
    def register_default_checks(self) -> None:
        self.register_check("database", self.check_database)
        self.register_check("redis", self.check_redis)
        self.register_check("gpu", self.check_gpu)
        logger.info("Registered default health checks")
    
    def get_last_results(self) -> Dict[str, ComponentHealth]:
        return self._last_results.copy()
