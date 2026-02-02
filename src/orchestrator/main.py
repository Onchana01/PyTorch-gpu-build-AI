import asyncio
import signal
from typing import Optional

import uvicorn

from src.orchestrator.coordinator import BuildCoordinator
from src.orchestrator.queue_manager import QueueManager
from src.orchestrator.priority_scheduler import PriorityScheduler
from src.orchestrator.resource_allocator import ResourceAllocator
from src.orchestrator.load_balancer import LoadBalancer, LoadBalancingStrategy
from src.orchestrator.state_manager import StateManager
from src.orchestrator.webhook_receiver import create_webhook_app
from src.common.config.settings import get_settings
from src.common.config.logging_config import setup_logging, get_logger


logger = get_logger(__name__)


class OrchestratorService:
    def __init__(self):
        self._settings = get_settings()
        self._coordinator: Optional[BuildCoordinator] = None
        self._load_balancer: Optional[LoadBalancer] = None
        self._shutdown_event = asyncio.Event()
    
    async def initialize(self) -> None:
        logger.info("Initializing Orchestrator Service")
        
        queue_manager = QueueManager(max_queue_size=1000)
        
        scheduler = PriorityScheduler()
        
        resource_allocator = ResourceAllocator()
        
        self._load_balancer = LoadBalancer(
            strategy=LoadBalancingStrategy.LEAST_CONNECTIONS,
            health_check_interval_seconds=30,
        )
        
        state_manager = StateManager()
        redis_url = self._settings.redis_url if hasattr(self._settings, 'redis_url') else None
        await state_manager.initialize(redis_url)
        
        self._coordinator = BuildCoordinator(
            queue_manager=queue_manager,
            scheduler=scheduler,
            resource_allocator=resource_allocator,
            load_balancer=self._load_balancer,
            state_manager=state_manager,
        )
        
        logger.info("Orchestrator Service initialized successfully")
    
    async def start(self) -> None:
        if not self._coordinator:
            await self.initialize()
        
        logger.info("Starting Orchestrator Service components")
        
        await self._coordinator.start()
        
        if self._load_balancer:
            await self._load_balancer.start()
        
        logger.info("Orchestrator Service started")
    
    async def stop(self) -> None:
        logger.info("Stopping Orchestrator Service")
        
        if self._coordinator:
            await self._coordinator.stop()
        
        if self._load_balancer:
            await self._load_balancer.stop()
        
        logger.info("Orchestrator Service stopped")
    
    def get_coordinator(self) -> Optional[BuildCoordinator]:
        return self._coordinator


async def run_orchestrator() -> None:
    setup_logging()
    settings = get_settings()
    
    logger.info("Starting ROCm CI/CD Orchestrator")
    
    orchestrator = OrchestratorService()
    
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Received shutdown signal")
        loop.create_task(orchestrator.stop())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            
    
    await orchestrator.start()
    
    app = create_webhook_app(coordinator=orchestrator.get_coordinator())
    
    config = uvicorn.Config(
        app=app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    
    try:
        await server.serve()
    except asyncio.CancelledError:
        
    finally:
        await orchestrator.stop()


def main() -> None:
    asyncio.run(run_orchestrator())


if __name__ == "__main__":
    main()
