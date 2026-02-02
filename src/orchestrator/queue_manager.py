from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from uuid import UUID
import asyncio
import heapq
from datetime import datetime, timezone

from src.common.dto.build import BuildRequest
from src.common.config.constants import Priority
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


@dataclass(order=True)
class QueueItem:
    priority_value: int
    timestamp: float
    request: BuildRequest = field(compare=False)
    
    @classmethod
    def from_request(cls, request: BuildRequest) -> "QueueItem":
        priority_value = cls._get_priority_value(request.priority)
        timestamp = datetime.now(timezone.utc).timestamp()
        return cls(priority_value=priority_value, timestamp=timestamp, request=request)
    
    @staticmethod
    def _get_priority_value(priority: Priority) -> int:
        priority_map = {
            Priority.CRITICAL: 0,
            Priority.HIGH: 100,
            Priority.NORMAL: 200,
            Priority.LOW: 300,
        }
        return priority_map.get(priority, 200)


class QueueManager:
    def __init__(self, max_queue_size: int = 1000):
        self._queue: List[QueueItem] = []
        self._queue_lock = asyncio.Lock()
        self._max_queue_size = max_queue_size
        self._build_ids: Dict[UUID, QueueItem] = {}
        self._queue_not_empty = asyncio.Event()
    
    async def enqueue(self, request: BuildRequest) -> bool:
        async with self._queue_lock:
            if len(self._queue) >= self._max_queue_size:
                logger.warning(f"Queue is full, cannot enqueue build {request.id}")
                return False
            
            if request.id in self._build_ids:
                logger.warning(f"Build {request.id} is already in the queue")
                return False
            
            item = QueueItem.from_request(request)
            heapq.heappush(self._queue, item)
            self._build_ids[request.id] = item
            self._queue_not_empty.set()
            
            logger.debug(f"Enqueued build {request.id} with priority {request.priority.value}")
            return True
    
    async def dequeue(self, timeout: Optional[float] = None) -> Optional[BuildRequest]:
        async with self._queue_lock:
            if not self._queue:
                self._queue_not_empty.clear()
        
        try:
            if timeout:
                await asyncio.wait_for(self._queue_not_empty.wait(), timeout=timeout)
            elif not self._queue:
                return None
        except asyncio.TimeoutError:
            return None
        
        async with self._queue_lock:
            if not self._queue:
                return None
            
            item = heapq.heappop(self._queue)
            self._build_ids.pop(item.request.id, None)
            
            if not self._queue:
                self._queue_not_empty.clear()
            
            logger.debug(f"Dequeued build {item.request.id}")
            return item.request
    
    async def peek(self) -> Optional[BuildRequest]:
        async with self._queue_lock:
            if not self._queue:
                return None
            return self._queue[0].request
    
    async def remove(self, build_id: UUID) -> bool:
        async with self._queue_lock:
            if build_id not in self._build_ids:
                return False
            
            item = self._build_ids.pop(build_id)
            
            try:
                self._queue.remove(item)
                heapq.heapify(self._queue)
                logger.debug(f"Removed build {build_id} from queue")
                return True
            except ValueError:
                return False
    
    async def get_queue_depth(self) -> int:
        async with self._queue_lock:
            return len(self._queue)
    
    async def get_queue_depth_by_priority(self) -> Dict[str, int]:
        async with self._queue_lock:
            counts: Dict[str, int] = {}
            for item in self._queue:
                priority_name = item.request.priority.value
                counts[priority_name] = counts.get(priority_name, 0) + 1
            return counts
    
    async def get_position(self, build_id: UUID) -> Optional[int]:
        async with self._queue_lock:
            if build_id not in self._build_ids:
                return None
            
            sorted_queue = sorted(self._queue)
            for i, item in enumerate(sorted_queue):
                if item.request.id == build_id:
                    return i + 1
            return None
    
    async def reprioritize(self, build_id: UUID, new_priority: Priority) -> bool:
        async with self._queue_lock:
            if build_id not in self._build_ids:
                return False
            
            old_item = self._build_ids.pop(build_id)
            
            try:
                self._queue.remove(old_item)
            except ValueError:
                return False
            
            old_item.request.priority = new_priority
            new_item = QueueItem.from_request(old_item.request)
            
            heapq.heappush(self._queue, new_item)
            self._build_ids[build_id] = new_item
            
            logger.info(f"Reprioritized build {build_id} to {new_priority.value}")
            return True
    
    async def clear(self) -> int:
        async with self._queue_lock:
            count = len(self._queue)
            self._queue.clear()
            self._build_ids.clear()
            self._queue_not_empty.clear()
            logger.info(f"Cleared {count} items from queue")
            return count
    
    async def get_all_items(self) -> List[BuildRequest]:
        async with self._queue_lock:
            sorted_queue = sorted(self._queue)
            return [item.request for item in sorted_queue]
    
    async def contains(self, build_id: UUID) -> bool:
        async with self._queue_lock:
            return build_id in self._build_ids
    
    async def get_estimated_wait_time(
        self,
        build_id: UUID,
        avg_build_time_seconds: float = 600.0,
    ) -> Optional[float]:
        position = await self.get_position(build_id)
        
        if position is None:
            return None
        
        return position * avg_build_time_seconds
