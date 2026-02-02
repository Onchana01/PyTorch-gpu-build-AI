from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from uuid import UUID
import asyncio
from datetime import datetime, timezone

from src.common.dto.build import BuildConfiguration
from src.common.dto.environment import GPUInfo
from src.common.config.constants import GPUArchitecture
from src.common.config.logging_config import get_logger
from src.common.config.settings import get_settings


logger = get_logger(__name__)


@dataclass
class ResourceAllocation:
    allocation_id: UUID
    gpu_ids: List[str] = field(default_factory=list)
    cpu_cores: int = 0
    memory_gb: float = 0.0
    node_name: str = ""
    allocated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "allocation_id": str(self.allocation_id),
            "gpu_ids": self.gpu_ids,
            "cpu_cores": self.cpu_cores,
            "memory_gb": self.memory_gb,
            "node_name": self.node_name,
            "allocated_at": self.allocated_at.isoformat(),
        }


@dataclass
class NodeResources:
    node_name: str
    total_gpus: int = 0
    available_gpus: int = 0
    gpu_ids: List[str] = field(default_factory=list)
    gpu_architectures: List[GPUArchitecture] = field(default_factory=list)
    total_cpu_cores: int = 0
    available_cpu_cores: int = 0
    total_memory_gb: float = 0.0
    available_memory_gb: float = 0.0
    is_healthy: bool = True
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ResourceAllocator:
    def __init__(self):
        self._nodes: Dict[str, NodeResources] = {}
        self._allocations: Dict[UUID, ResourceAllocation] = {}
        self._lock = asyncio.Lock()
        self._settings = get_settings()
        self._k8s_client = None
        self._initialize_k8s_client()
    
    def _initialize_k8s_client(self) -> None:
        try:
            from kubernetes import client, config
            
            try:
                config.load_incluster_config()
            except config.ConfigException:
                try:
                    config.load_kube_config()
                except config.ConfigException:
                    logger.warning("Kubernetes config not available, running in standalone mode")
                    return
            
            self._k8s_client = client.CoreV1Api()
            logger.info("Kubernetes client initialized successfully")
        except ImportError:
            logger.warning("Kubernetes library not installed")
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
    
    async def refresh_node_resources(self) -> None:
        if self._k8s_client is None:
            await self._refresh_local_resources()
            return
        
        try:
            nodes = self._k8s_client.list_node()
            
            for node in nodes.items:
                node_name = node.metadata.name
                
                labels = node.metadata.labels or {}
                if labels.get("gpu-vendor") != "amd":
                    continue
                
                allocatable = node.status.allocatable or {}
                capacity = node.status.capacity or {}
                
                gpu_count = int(allocatable.get("amd.com/gpu", 0))
                cpu_cores = self._parse_cpu_quantity(allocatable.get("cpu", "0"))
                memory_gb = self._parse_memory_quantity(allocatable.get("memory", "0")) / (1024 ** 3)
                
                gpu_arch_str = labels.get("gpu-arch", "gfx90a")
                try:
                    gpu_arch = GPUArchitecture(gpu_arch_str)
                except ValueError:
                    gpu_arch = GPUArchitecture.GFX90A
                
                async with self._lock:
                    if node_name not in self._nodes:
                        self._nodes[node_name] = NodeResources(node_name=node_name)
                    
                    node_resources = self._nodes[node_name]
                    node_resources.total_gpus = gpu_count
                    node_resources.available_gpus = gpu_count
                    node_resources.gpu_ids = [f"{node_name}-gpu-{i}" for i in range(gpu_count)]
                    node_resources.gpu_architectures = [gpu_arch] * gpu_count
                    node_resources.total_cpu_cores = cpu_cores
                    node_resources.available_cpu_cores = cpu_cores
                    node_resources.total_memory_gb = memory_gb
                    node_resources.available_memory_gb = memory_gb
                    node_resources.is_healthy = self._is_node_healthy(node)
                    node_resources.last_updated = datetime.now(timezone.utc)
            
            logger.debug(f"Refreshed resources for {len(self._nodes)} nodes")
        except Exception as e:
            logger.error(f"Failed to refresh node resources: {e}")
    
    async def _refresh_local_resources(self) -> None:
        import os
        import psutil
        
        node_name = "local"
        
        async with self._lock:
            if node_name not in self._nodes:
                self._nodes[node_name] = NodeResources(node_name=node_name)
            
            node = self._nodes[node_name]
            node.total_cpu_cores = os.cpu_count() or 4
            node.available_cpu_cores = node.total_cpu_cores
            node.total_memory_gb = psutil.virtual_memory().total / (1024 ** 3)
            node.available_memory_gb = psutil.virtual_memory().available / (1024 ** 3)
            
            gpu_count = self._detect_local_gpus()
            node.total_gpus = gpu_count
            node.available_gpus = gpu_count
            node.gpu_ids = [f"gpu-{i}" for i in range(gpu_count)]
            node.gpu_architectures = [GPUArchitecture.GFX90A] * gpu_count
            node.is_healthy = True
            node.last_updated = datetime.now(timezone.utc)
    
    def _detect_local_gpus(self) -> int:
        try:
            import subprocess
            result = subprocess.run(
                ["rocm-smi", "--showid"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                gpu_lines = [l for l in lines if "GPU" in l]
                return len(gpu_lines)
        except Exception as e:
            logger.debug(f"Failed to detect local GPUs via rocm-smi: {e}")
        return 0
    
    def _parse_cpu_quantity(self, quantity: str) -> int:
        if quantity.endswith("m"):
            return int(quantity[:-1]) // 1000
        return int(quantity)
    
    def _parse_memory_quantity(self, quantity: str) -> int:
        suffixes = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4}
        for suffix, multiplier in suffixes.items():
            if quantity.endswith(suffix):
                return int(quantity[:-len(suffix)]) * multiplier
        return int(quantity)
    
    def _is_node_healthy(self, node: Any) -> bool:
        if not hasattr(node, "status") or not hasattr(node.status, "conditions"):
            return True
        
        for condition in node.status.conditions or []:
            if condition.type == "Ready" and condition.status == "True":
                return True
        return False
    
    async def allocate_resources(
        self,
        config: BuildConfiguration,
    ) -> Optional[ResourceAllocation]:
        await self.refresh_node_resources()
        
        required_gpus = 1
        required_cpu = config.cpu_cores or 8
        required_memory = config.memory_gb or 32.0
        required_arch = config.gpu_architecture
        
        async with self._lock:
            selected_node: Optional[NodeResources] = None
            
            for node in self._nodes.values():
                if not node.is_healthy:
                    continue
                
                if node.available_gpus < required_gpus:
                    continue
                
                if node.available_cpu_cores < required_cpu:
                    continue
                
                if node.available_memory_gb < required_memory:
                    continue
                
                if required_arch and required_arch not in node.gpu_architectures:
                    continue
                
                if selected_node is None or node.available_gpus > selected_node.available_gpus:
                    selected_node = node
            
            if selected_node is None:
                logger.warning("No suitable node found for resource allocation")
                return None
            
            allocated_gpu_ids = selected_node.gpu_ids[:required_gpus]
            
            selected_node.available_gpus -= required_gpus
            selected_node.available_cpu_cores -= required_cpu
            selected_node.available_memory_gb -= required_memory
            
            from uuid import uuid4
            allocation = ResourceAllocation(
                allocation_id=uuid4(),
                gpu_ids=allocated_gpu_ids,
                cpu_cores=required_cpu,
                memory_gb=required_memory,
                node_name=selected_node.node_name,
            )
            
            self._allocations[allocation.allocation_id] = allocation
            
            logger.info(
                f"Allocated resources on {selected_node.node_name}: "
                f"{len(allocated_gpu_ids)} GPUs, {required_cpu} cores, {required_memory}GB memory"
            )
            
            return allocation
    
    async def release_resources(self, allocation: ResourceAllocation) -> bool:
        async with self._lock:
            if allocation.allocation_id not in self._allocations:
                logger.warning(f"Allocation {allocation.allocation_id} not found")
                return False
            
            del self._allocations[allocation.allocation_id]
            
            if allocation.node_name in self._nodes:
                node = self._nodes[allocation.node_name]
                node.available_gpus += len(allocation.gpu_ids)
                node.available_cpu_cores += allocation.cpu_cores
                node.available_memory_gb += allocation.memory_gb
            
            logger.info(f"Released resources from allocation {allocation.allocation_id}")
            return True
    
    async def get_available_resources(self) -> Dict[str, Any]:
        await self.refresh_node_resources()
        
        async with self._lock:
            total_gpus = sum(n.available_gpus for n in self._nodes.values() if n.is_healthy)
            total_cpu = sum(n.available_cpu_cores for n in self._nodes.values() if n.is_healthy)
            total_memory = sum(n.available_memory_gb for n in self._nodes.values() if n.is_healthy)
            
            return {
                "gpu_count": total_gpus,
                "cpu_cores": total_cpu,
                "memory_gb": total_memory,
                "healthy_nodes": sum(1 for n in self._nodes.values() if n.is_healthy),
                "total_nodes": len(self._nodes),
            }
    
    async def get_node_status(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return [
                {
                    "node_name": node.node_name,
                    "total_gpus": node.total_gpus,
                    "available_gpus": node.available_gpus,
                    "total_cpu_cores": node.total_cpu_cores,
                    "available_cpu_cores": node.available_cpu_cores,
                    "total_memory_gb": node.total_memory_gb,
                    "available_memory_gb": node.available_memory_gb,
                    "is_healthy": node.is_healthy,
                    "gpu_architectures": [arch.value for arch in node.gpu_architectures],
                }
                for node in self._nodes.values()
            ]
