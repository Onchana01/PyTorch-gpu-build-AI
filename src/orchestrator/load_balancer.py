from typing import List, Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass, field
import asyncio
from datetime import datetime, timezone
import random

from src.common.dto.build import BuildRequest
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class LoadBalancingStrategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    RANDOM = "random"
    RESOURCE_AWARE = "resource_aware"


@dataclass
class WorkerInfo:
    worker_id: str
    address: str
    port: int = 8080
    weight: int = 1
    current_load: int = 0
    max_load: int = 5
    is_healthy: bool = True
    last_health_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_builds_completed: int = 0
    average_build_time_seconds: float = 600.0
    
    @property
    def available_capacity(self) -> int:
        return max(0, self.max_load - self.current_load)
    
    @property
    def load_percentage(self) -> float:
        if self.max_load == 0:
            return 100.0
        return (self.current_load / self.max_load) * 100


class LoadBalancer:
    def __init__(
        self,
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_CONNECTIONS,
        health_check_interval_seconds: int = 30,
    ):
        self._strategy = strategy
        self._workers: Dict[str, WorkerInfo] = {}
        self._lock = asyncio.Lock()
        self._round_robin_index = 0
        self._health_check_interval = health_check_interval_seconds
        self._health_check_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info(f"Load balancer started with strategy: {self._strategy.value}")
    
    async def stop(self) -> None:
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                logger.debug("Health check task cancelled successfully")
        logger.info("Load balancer stopped")
    
    async def register_worker(
        self,
        worker_id: str,
        address: str,
        port: int = 8080,
        weight: int = 1,
        max_load: int = 5,
    ) -> None:
        async with self._lock:
            self._workers[worker_id] = WorkerInfo(
                worker_id=worker_id,
                address=address,
                port=port,
                weight=weight,
                max_load=max_load,
            )
            logger.info(f"Registered worker {worker_id} at {address}:{port}")
    
    async def unregister_worker(self, worker_id: str) -> bool:
        async with self._lock:
            if worker_id in self._workers:
                del self._workers[worker_id]
                logger.info(f"Unregistered worker {worker_id}")
                return True
            return False
    
    async def select_worker(
        self,
        request: BuildRequest,
    ) -> Optional[str]:
        async with self._lock:
            available_workers = [
                w for w in self._workers.values()
                if w.is_healthy and w.current_load < w.max_load
            ]
            
            if not available_workers:
                logger.warning("No available workers for build request")
                return None
            
            selected = self._select_by_strategy(available_workers, request)
            
            if selected:
                selected.current_load += 1
                logger.debug(f"Selected worker {selected.worker_id} (load: {selected.current_load}/{selected.max_load})")
                return selected.worker_id
            
            return None
    
    def _select_by_strategy(
        self,
        workers: List[WorkerInfo],
        request: BuildRequest,
    ) -> Optional[WorkerInfo]:
        if not workers:
            return None
        
        if self._strategy == LoadBalancingStrategy.ROUND_ROBIN:
            return self._select_round_robin(workers)
        elif self._strategy == LoadBalancingStrategy.LEAST_CONNECTIONS:
            return self._select_least_connections(workers)
        elif self._strategy == LoadBalancingStrategy.WEIGHTED_ROUND_ROBIN:
            return self._select_weighted_round_robin(workers)
        elif self._strategy == LoadBalancingStrategy.RANDOM:
            return self._select_random(workers)
        elif self._strategy == LoadBalancingStrategy.RESOURCE_AWARE:
            return self._select_resource_aware(workers, request)
        else:
            return self._select_least_connections(workers)
    
    def _select_round_robin(self, workers: List[WorkerInfo]) -> WorkerInfo:
        self._round_robin_index = (self._round_robin_index + 1) % len(workers)
        return workers[self._round_robin_index]
    
    def _select_least_connections(self, workers: List[WorkerInfo]) -> WorkerInfo:
        return min(workers, key=lambda w: w.current_load)
    
    def _select_weighted_round_robin(self, workers: List[WorkerInfo]) -> WorkerInfo:
        total_weight = sum(w.weight * w.available_capacity for w in workers)
        if total_weight == 0:
            return self._select_least_connections(workers)
        
        target = random.randint(1, total_weight)
        current = 0
        
        for worker in workers:
            current += worker.weight * worker.available_capacity
            if current >= target:
                return worker
        
        return workers[-1]
    
    def _select_random(self, workers: List[WorkerInfo]) -> WorkerInfo:
        return random.choice(workers)
    
    def _select_resource_aware(
        self,
        workers: List[WorkerInfo],
        request: BuildRequest,
    ) -> WorkerInfo:
        scored_workers = []
        
        for worker in workers:
            score = 0.0
            
            load_score = 1.0 - (worker.current_load / max(worker.max_load, 1))
            score += load_score * 0.4
            
            capacity_score = worker.available_capacity / max(worker.max_load, 1)
            score += capacity_score * 0.3
            
            if worker.total_builds_completed > 0:
                efficiency_score = 600.0 / max(worker.average_build_time_seconds, 1)
                score += min(efficiency_score, 1.0) * 0.3
            else:
                score += 0.15
            
            scored_workers.append((worker, score))
        
        scored_workers.sort(key=lambda x: x[1], reverse=True)
        return scored_workers[0][0]
    
    async def update_worker_load(
        self,
        worker_id: str,
        load_delta: int,
    ) -> None:
        async with self._lock:
            if worker_id in self._workers:
                worker = self._workers[worker_id]
                worker.current_load = max(0, worker.current_load + load_delta)
                logger.debug(f"Updated worker {worker_id} load to {worker.current_load}")
    
    async def record_build_completion(
        self,
        worker_id: str,
        build_time_seconds: float,
    ) -> None:
        async with self._lock:
            if worker_id in self._workers:
                worker = self._workers[worker_id]
                worker.current_load = max(0, worker.current_load - 1)
                worker.total_builds_completed += 1
                
                old_avg = worker.average_build_time_seconds
                n = worker.total_builds_completed
                worker.average_build_time_seconds = ((n - 1) * old_avg + build_time_seconds) / n
    
    async def mark_worker_unhealthy(self, worker_id: str) -> None:
        async with self._lock:
            if worker_id in self._workers:
                self._workers[worker_id].is_healthy = False
                logger.warning(f"Marked worker {worker_id} as unhealthy")
    
    async def mark_worker_healthy(self, worker_id: str) -> None:
        async with self._lock:
            if worker_id in self._workers:
                self._workers[worker_id].is_healthy = True
                self._workers[worker_id].last_health_check = datetime.now(timezone.utc)
                logger.info(f"Marked worker {worker_id} as healthy")
    
    async def _health_check_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._perform_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
    
    async def _perform_health_checks(self) -> None:
        async with self._lock:
            worker_ids = list(self._workers.keys())
        
        for worker_id in worker_ids:
            try:
                is_healthy = await self._check_worker_health(worker_id)
                if is_healthy:
                    await self.mark_worker_healthy(worker_id)
                else:
                    await self.mark_worker_unhealthy(worker_id)
            except Exception as e:
                logger.warning(f"Health check failed for worker {worker_id}: {e}")
                await self.mark_worker_unhealthy(worker_id)
    
    async def _check_worker_health(self, worker_id: str) -> bool:
        async with self._lock:
            if worker_id not in self._workers:
                return False
            worker = self._workers[worker_id]
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                url = f"http://{worker.address}:{worker.port}/health"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    return response.status == 200
        except Exception:
            return True
    
    async def get_worker_stats(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return [
                {
                    "worker_id": w.worker_id,
                    "address": f"{w.address}:{w.port}",
                    "current_load": w.current_load,
                    "max_load": w.max_load,
                    "load_percentage": w.load_percentage,
                    "is_healthy": w.is_healthy,
                    "total_builds_completed": w.total_builds_completed,
                    "average_build_time_seconds": w.average_build_time_seconds,
                }
                for w in self._workers.values()
            ]
    
    def set_strategy(self, strategy: LoadBalancingStrategy) -> None:
        self._strategy = strategy
        logger.info(f"Load balancing strategy changed to: {strategy.value}")
