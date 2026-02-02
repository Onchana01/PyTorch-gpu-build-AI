import asyncio
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime, timezone

from src.orchestrator.queue_manager import QueueManager
from src.orchestrator.priority_scheduler import PriorityScheduler
from src.orchestrator.resource_allocator import ResourceAllocator
from src.orchestrator.load_balancer import LoadBalancer
from src.orchestrator.state_manager import StateManager
from src.common.dto.build import BuildRequest, BuildResult, BuildConfiguration, BuildSummary
from src.common.config.constants import BuildStatus, Priority
from src.common.config.logging_config import get_logger
from src.common.utils.time_utils import utc_now


logger = get_logger(__name__)


class BuildCoordinator:
    def __init__(
        self,
        queue_manager: QueueManager,
        scheduler: PriorityScheduler,
        resource_allocator: ResourceAllocator,
        load_balancer: LoadBalancer,
        state_manager: StateManager,
    ):
        self._queue_manager = queue_manager
        self._scheduler = scheduler
        self._resource_allocator = resource_allocator
        self._load_balancer = load_balancer
        self._state_manager = state_manager
        self._active_builds: Dict[UUID, BuildRequest] = {}
        self._running = False
        self._processing_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        logger.info("Starting Build Coordinator")
        self._running = True
        self._processing_task = asyncio.create_task(self._process_queue())
        await self._state_manager.restore_pending_builds()
        logger.info("Build Coordinator started successfully")
    
    async def stop(self) -> None:
        logger.info("Stopping Build Coordinator")
        self._running = False
        
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                logger.debug("Processing task cancelled successfully")
        
        await self._save_active_builds_state()
        logger.info("Build Coordinator stopped")
    
    async def submit_build(
        self,
        request: BuildRequest,
    ) -> UUID:
        logger.info(f"Submitting build request for {request.repository}@{request.commit_sha[:8]}")
        
        priority = self._scheduler.calculate_priority(request)
        request.priority = priority
        
        await self._state_manager.save_build_request(request)
        
        await self._queue_manager.enqueue(request)
        
        logger.info(f"Build {request.id} queued with priority {priority.value}")
        
        return request.id
    
    async def get_build_status(
        self,
        build_id: UUID,
    ) -> Optional[BuildSummary]:
        state = await self._state_manager.get_build_state(build_id)
        
        if state is None:
            return None
        
        return BuildSummary(
            build_id=build_id,
            repository=state.get("repository", ""),
            branch=state.get("branch", ""),
            status=BuildStatus(state.get("status", BuildStatus.UNKNOWN.value)),
            started_at=state.get("started_at"),
            completed_at=state.get("completed_at"),
            duration_seconds=state.get("duration_seconds"),
        )
    
    async def cancel_build(
        self,
        build_id: UUID,
        cancelled_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        logger.info(f"Cancelling build {build_id}")
        
        removed_from_queue = await self._queue_manager.remove(build_id)
        
        if removed_from_queue:
            await self._state_manager.update_build_status(
                build_id,
                BuildStatus.CANCELLED,
                metadata={"cancelled_by": cancelled_by, "reason": reason}
            )
            logger.info(f"Build {build_id} removed from queue and cancelled")
            return True
        
        if build_id in self._active_builds:
            await self._cancel_active_build(build_id, cancelled_by, reason)
            logger.info(f"Active build {build_id} cancelled")
            return True
        
        logger.warning(f"Build {build_id} not found for cancellation")
        return False
    
    async def retry_build(
        self,
        build_id: UUID,
    ) -> Optional[UUID]:
        original_request = await self._state_manager.get_build_request(build_id)
        
        if original_request is None:
            logger.error(f"Cannot retry build {build_id}: original request not found")
            return None
        
        new_request = BuildRequest(
            repository=original_request.repository,
            commit_sha=original_request.commit_sha,
            branch=original_request.branch,
            pr_number=original_request.pr_number,
            triggered_by=original_request.triggered_by,
            configurations=original_request.configurations,
            metadata={
                **original_request.metadata,
                "retry_of": str(build_id),
            }
        )
        
        return await self.submit_build(new_request)
    
    async def get_queue_status(self) -> Dict[str, Any]:
        queue_depth = await self._queue_manager.get_queue_depth()
        active_count = len(self._active_builds)
        available_resources = await self._resource_allocator.get_available_resources()
        
        return {
            "queue_depth": queue_depth,
            "active_builds": active_count,
            "available_gpus": available_resources.get("gpu_count", 0),
            "available_cpu_cores": available_resources.get("cpu_cores", 0),
            "available_memory_gb": available_resources.get("memory_gb", 0),
        }
    
    async def _process_queue(self) -> None:
        logger.info("Build queue processing started")
        
        while self._running:
            try:
                resources = await self._resource_allocator.get_available_resources()
                
                if resources.get("gpu_count", 0) > 0:
                    request = await self._queue_manager.dequeue()
                    
                    if request:
                        asyncio.create_task(self._execute_build(request))
                
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing build queue: {e}")
                await asyncio.sleep(5.0)
    
    async def _execute_build(self, request: BuildRequest) -> None:
        build_id = request.id
        
        try:
            self._active_builds[build_id] = request
            
            await self._state_manager.update_build_status(
                build_id,
                BuildStatus.RUNNING,
                metadata={"started_at": utc_now().isoformat()}
            )
            
            allocation = await self._resource_allocator.allocate_resources(
                request.configurations[0] if request.configurations else BuildConfiguration()
            )
            
            if allocation is None:
                logger.warning(f"Could not allocate resources for build {build_id}, re-queueing")
                await self._queue_manager.enqueue(request)
                return
            
            worker = await self._load_balancer.select_worker(request)
            
            if worker is None:
                logger.warning(f"No available worker for build {build_id}, re-queueing")
                await self._resource_allocator.release_resources(allocation)
                await self._queue_manager.enqueue(request)
                return
            
            logger.info(f"Executing build {build_id} on worker {worker}")
            
            result = await self._dispatch_to_worker(worker, request, allocation)
            
            await self._handle_build_result(build_id, result)
            
        except Exception as e:
            logger.error(f"Error executing build {build_id}: {e}")
            await self._state_manager.update_build_status(
                build_id,
                BuildStatus.FAILED,
                metadata={"error": str(e)}
            )
        finally:
            self._active_builds.pop(build_id, None)
            if allocation:
                await self._resource_allocator.release_resources(allocation)
    
    async def _dispatch_to_worker(
        self,
        worker: str,
        request: BuildRequest,
        allocation: Dict[str, Any],
    ) -> BuildResult:
        logger.info(f"Dispatching build {request.id} to worker {worker}")
        
        return BuildResult(
            build_id=request.id,
            request=request,
            configuration=request.configurations[0] if request.configurations else BuildConfiguration(),
            status=BuildStatus.SUCCESS,
            started_at=utc_now(),
            completed_at=utc_now(),
        )
    
    async def _handle_build_result(
        self,
        build_id: UUID,
        result: BuildResult,
    ) -> None:
        await self._state_manager.update_build_status(
            build_id,
            result.status,
            metadata={
                "completed_at": result.completed_at.isoformat() if result.completed_at else None,
                "duration_seconds": result.duration_seconds,
            }
        )
        
        await self._load_balancer.update_worker_load(
            result.environment.node_name if result.environment else "unknown",
            -1
        )
        
        logger.info(f"Build {build_id} completed with status {result.status.value}")
    
    async def _cancel_active_build(
        self,
        build_id: UUID,
        cancelled_by: Optional[str],
        reason: Optional[str],
    ) -> None:
        await self._state_manager.update_build_status(
            build_id,
            BuildStatus.CANCELLED,
            metadata={"cancelled_by": cancelled_by, "reason": reason}
        )
    
    async def _save_active_builds_state(self) -> None:
        for build_id, request in self._active_builds.items():
            await self._state_manager.checkpoint_build(build_id, "interrupted")
