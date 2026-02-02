from typing import Dict, Optional, Any, List
from uuid import UUID
import asyncio
import json
from datetime import datetime, timezone

from src.common.dto.build import BuildRequest, BuildResult
from src.common.config.constants import BuildStatus
from src.common.config.logging_config import get_logger
from src.common.utils.time_utils import utc_now


logger = get_logger(__name__)


class StateManager:
    def __init__(self):
        self._build_states: Dict[UUID, Dict[str, Any]] = {}
        self._build_requests: Dict[UUID, BuildRequest] = {}
        self._checkpoints: Dict[UUID, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._redis_client = None
        self._persistence_enabled = False
    
    async def initialize(self, redis_url: Optional[str] = None) -> None:
        if redis_url:
            try:
                import redis.asyncio as redis
                self._redis_client = redis.from_url(redis_url)
                self._persistence_enabled = True
                logger.info("State manager initialized with Redis persistence")
            except ImportError:
                logger.warning("Redis library not installed, using in-memory state")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
    
    async def save_build_request(self, request: BuildRequest) -> None:
        async with self._lock:
            self._build_requests[request.id] = request
            self._build_states[request.id] = {
                "status": BuildStatus.PENDING.value,
                "repository": request.repository,
                "branch": request.branch,
                "commit_sha": request.commit_sha,
                "pr_number": request.pr_number,
                "created_at": utc_now().isoformat(),
            }
        
        if self._persistence_enabled:
            await self._persist_state(request.id)
        
        logger.debug(f"Saved build request state for {request.id}")
    
    async def get_build_request(self, build_id: UUID) -> Optional[BuildRequest]:
        async with self._lock:
            request = self._build_requests.get(build_id)
        
        if request is None and self._persistence_enabled:
            request = await self._load_request_from_redis(build_id)
        
        return request
    
    async def get_build_state(self, build_id: UUID) -> Optional[Dict[str, Any]]:
        async with self._lock:
            state = self._build_states.get(build_id)
        
        if state is None and self._persistence_enabled:
            state = await self._load_state_from_redis(build_id)
        
        return state
    
    async def update_build_status(
        self,
        build_id: UUID,
        status: BuildStatus,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self._lock:
            if build_id not in self._build_states:
                self._build_states[build_id] = {}
            
            self._build_states[build_id]["status"] = status.value
            self._build_states[build_id]["updated_at"] = utc_now().isoformat()
            
            if metadata:
                self._build_states[build_id].update(metadata)
            
            if status in (BuildStatus.SUCCESS, BuildStatus.FAILED, BuildStatus.CANCELLED):
                self._build_states[build_id]["completed_at"] = utc_now().isoformat()
        
        if self._persistence_enabled:
            await self._persist_state(build_id)
        
        logger.debug(f"Updated build {build_id} status to {status.value}")
    
    async def checkpoint_build(
        self,
        build_id: UUID,
        stage: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        checkpoint = {
            "stage": stage,
            "timestamp": utc_now().isoformat(),
            "data": data or {},
        }
        
        async with self._lock:
            if build_id not in self._checkpoints:
                self._checkpoints[build_id] = {"checkpoints": []}
            
            self._checkpoints[build_id]["checkpoints"].append(checkpoint)
            self._checkpoints[build_id]["latest_stage"] = stage
        
        if self._persistence_enabled:
            await self._persist_checkpoint(build_id)
        
        logger.debug(f"Checkpointed build {build_id} at stage {stage}")
    
    async def get_latest_checkpoint(self, build_id: UUID) -> Optional[Dict[str, Any]]:
        async with self._lock:
            checkpoint_data = self._checkpoints.get(build_id)
            
            if checkpoint_data and checkpoint_data.get("checkpoints"):
                return checkpoint_data["checkpoints"][-1]
        
        if self._persistence_enabled:
            return await self._load_checkpoint_from_redis(build_id)
        
        return None
    
    async def restore_pending_builds(self) -> List[BuildRequest]:
        restored_builds: List[BuildRequest] = []
        
        if self._persistence_enabled:
            restored_builds = await self._load_pending_builds_from_redis()
        
        async with self._lock:
            for build_id, state in self._build_states.items():
                if state.get("status") in (BuildStatus.PENDING.value, BuildStatus.RUNNING.value):
                    request = self._build_requests.get(build_id)
                    if request and request not in restored_builds:
                        restored_builds.append(request)
        
        logger.info(f"Restored {len(restored_builds)} pending builds")
        return restored_builds
    
    async def save_state(self, key: str, value: Any) -> None:
        if self._persistence_enabled and self._redis_client:
            try:
                serialized = json.dumps(value, default=str)
                await self._redis_client.set(f"state:{key}", serialized)
            except Exception as e:
                logger.error(f"Failed to save state for key {key}: {e}")
    
    async def restore_state(self, key: str) -> Optional[Any]:
        if self._persistence_enabled and self._redis_client:
            try:
                data = await self._redis_client.get(f"state:{key}")
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.error(f"Failed to restore state for key {key}: {e}")
        return None
    
    async def delete_build_state(self, build_id: UUID) -> None:
        async with self._lock:
            self._build_states.pop(build_id, None)
            self._build_requests.pop(build_id, None)
            self._checkpoints.pop(build_id, None)
        
        if self._persistence_enabled and self._redis_client:
            try:
                await self._redis_client.delete(
                    f"build:request:{build_id}",
                    f"build:state:{build_id}",
                    f"build:checkpoint:{build_id}",
                )
            except Exception as e:
                logger.error(f"Failed to delete build state from Redis: {e}")
    
    async def get_all_active_builds(self) -> Dict[UUID, Dict[str, Any]]:
        active_builds: Dict[UUID, Dict[str, Any]] = {}
        
        async with self._lock:
            for build_id, state in self._build_states.items():
                if state.get("status") in (BuildStatus.PENDING.value, BuildStatus.RUNNING.value):
                    active_builds[build_id] = state.copy()
        
        return active_builds
    
    async def _persist_state(self, build_id: UUID) -> None:
        if not self._redis_client:
            return
        
        try:
            async with self._lock:
                state = self._build_states.get(build_id)
                request = self._build_requests.get(build_id)
            
            if state:
                await self._redis_client.set(
                    f"build:state:{build_id}",
                    json.dumps(state, default=str),
                    ex=86400 * 7
                )
            
            if request:
                await self._redis_client.set(
                    f"build:request:{build_id}",
                    request.model_dump_json(),
                    ex=86400 * 7
                )
        except Exception as e:
            logger.error(f"Failed to persist state for build {build_id}: {e}")
    
    async def _persist_checkpoint(self, build_id: UUID) -> None:
        if not self._redis_client:
            return
        
        try:
            async with self._lock:
                checkpoint_data = self._checkpoints.get(build_id)
            
            if checkpoint_data:
                await self._redis_client.set(
                    f"build:checkpoint:{build_id}",
                    json.dumps(checkpoint_data, default=str),
                    ex=86400 * 7
                )
        except Exception as e:
            logger.error(f"Failed to persist checkpoint for build {build_id}: {e}")
    
    async def _load_state_from_redis(self, build_id: UUID) -> Optional[Dict[str, Any]]:
        if not self._redis_client:
            return None
        
        try:
            data = await self._redis_client.get(f"build:state:{build_id}")
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"Failed to load state from Redis for build {build_id}: {e}")
        
        return None
    
    async def _load_request_from_redis(self, build_id: UUID) -> Optional[BuildRequest]:
        if not self._redis_client:
            return None
        
        try:
            data = await self._redis_client.get(f"build:request:{build_id}")
            if data:
                return BuildRequest.model_validate_json(data)
        except Exception as e:
            logger.error(f"Failed to load request from Redis for build {build_id}: {e}")
        
        return None
    
    async def _load_checkpoint_from_redis(self, build_id: UUID) -> Optional[Dict[str, Any]]:
        if not self._redis_client:
            return None
        
        try:
            data = await self._redis_client.get(f"build:checkpoint:{build_id}")
            if data:
                checkpoint_data = json.loads(data)
                if checkpoint_data.get("checkpoints"):
                    return checkpoint_data["checkpoints"][-1]
        except Exception as e:
            logger.error(f"Failed to load checkpoint from Redis for build {build_id}: {e}")
        
        return None
    
    async def _load_pending_builds_from_redis(self) -> List[BuildRequest]:
        if not self._redis_client:
            return []
        
        pending_builds: List[BuildRequest] = []
        
        try:
            cursor: int = 0
            while True:
                cursor, keys = await self._redis_client.scan(
                    cursor=cursor,
                    match="build:state:*",
                    count=100
                )
                
                for key in keys:
                    state_data = await self._redis_client.get(key)
                    if state_data:
                        state = json.loads(state_data)
                        if state.get("status") in (BuildStatus.PENDING.value, BuildStatus.RUNNING.value):
                            build_id = key.decode().split(":")[-1]
                            request = await self._load_request_from_redis(UUID(build_id))
                            if request:
                                pending_builds.append(request)
                
                if cursor == 0:
                    break
        except Exception as e:
            logger.error(f"Failed to load pending builds from Redis: {e}")
        
        return pending_builds
