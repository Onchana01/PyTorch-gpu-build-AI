from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import asyncio
import os
import subprocess
import re
from pathlib import Path
from datetime import datetime, timezone

from src.common.dto.environment import (
    EnvironmentSnapshot, ROCmEnvironment, GPUInfo, CompilerInfo, SystemInfo
)
from src.common.config.constants import ROCmVersion, GPUArchitecture
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class EnvironmentManager:
    def __init__(self, rocm_path: str = "/opt/rocm"):
        self._rocm_path = Path(rocm_path)
    
    async def capture_snapshot(self) -> Optional[EnvironmentSnapshot]:
        try:
            rocm_env = await self._get_rocm_environment()
            gpus = await self._get_gpu_info()
            compiler = await self._get_compiler_info()
            system = await self._get_system_info()
            
            return EnvironmentSnapshot(
                rocm=rocm_env,
                gpus=gpus,
                compiler=compiler,
                system=system,
                captured_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(f"Failed to capture environment snapshot: {e}")
            return None
    
    async def _get_rocm_environment(self) -> Optional[ROCmEnvironment]:
        version_file = self._rocm_path / ".info" / "version"
        version = "unknown"
        
        if version_file.exists():
            version = version_file.read_text().strip()
        else:
            try:
                result = await self._run_command(["rocminfo", "--version"])
                if result:
                    match = re.search(r"(\d+\.\d+\.?\d*)", result)
                    if match:
                        version = match.group(1)
            except Exception as e:
                logger.debug(f"Failed to detect ROCm version via rocminfo: {e}")
        
        return ROCmEnvironment(
            version=version,
            path=str(self._rocm_path),
            hip_version=await self._get_hip_version(),
        )
    
    async def _get_hip_version(self) -> Optional[str]:
        try:
            result = await self._run_command([str(self._rocm_path / "bin" / "hipcc"), "--version"])
            if result:
                match = re.search(r"HIP version: ([\d.]+)", result)
                if match:
                    return match.group(1)
        except Exception as e:
            logger.debug(f"Failed to detect HIP version: {e}")
        return None
    
    async def _get_gpu_info(self) -> List[GPUInfo]:
        gpus = []
        
        try:
            result = await self._run_command(["rocm-smi", "--showid", "--showproductname", "--showmeminfo", "vram"])
            if result:
                gpu_id = None
                gpu_name = None
                
                for line in result.split("\n"):
                    if "GPU" in line and "[" in line:
                        id_match = re.search(r"GPU\[(\d+)\]", line)
                        if id_match:
                            if gpu_id is not None:
                                gpus.append(GPUInfo(device_id=int(gpu_id), name=gpu_name or "Unknown"))
                            gpu_id = id_match.group(1)
                    
                    if "Card series" in line or "Product" in line:
                        gpu_name = line.split(":")[-1].strip()
                
                if gpu_id is not None:
                    gpus.append(GPUInfo(device_id=int(gpu_id), name=gpu_name or "Unknown"))
        except Exception as e:
            logger.warning(f"Failed to get GPU info: {e}")
        
        return gpus
    
    async def _get_compiler_info(self) -> Optional[CompilerInfo]:
        try:
            hipcc_path = self._rocm_path / "bin" / "hipcc"
            result = await self._run_command([str(hipcc_path), "--version"])
            
            if result:
                version = "unknown"
                match = re.search(r"HIP version: ([\d.]+)", result)
                if match:
                    version = match.group(1)
                
                return CompilerInfo(
                    name="hipcc",
                    version=version,
                    path=str(hipcc_path),
                )
        except Exception as e:
            logger.debug(f"Failed to get compiler info: {e}")
        return None
    
    async def _get_system_info(self) -> SystemInfo:
        import platform
        
        cpu_count = os.cpu_count() or 0
        
        try:
            import psutil
            total_memory = psutil.virtual_memory().total / (1024 ** 3)
            available_memory = psutil.virtual_memory().available / (1024 ** 3)
        except ImportError:
            total_memory = 0.0
            available_memory = 0.0
        
        return SystemInfo(
            os_name=platform.system(),
            os_version=platform.release(),
            kernel_version=platform.version(),
            cpu_count=cpu_count,
            total_memory_gb=total_memory,
            available_memory_gb=available_memory,
            hostname=platform.node(),
        )
    
    async def _run_command(self, cmd: List[str]) -> Optional[str]:
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            return stdout.decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"Command {cmd[0]} failed: {e}")
            return None
    
    async def validate_environment(self) -> Dict[str, Any]:
        issues = []
        
        if not self._rocm_path.exists():
            issues.append(f"ROCm path {self._rocm_path} does not exist")
        
        hipcc = self._rocm_path / "bin" / "hipcc"
        if not hipcc.exists():
            issues.append("hipcc compiler not found")
        
        gpus = await self._get_gpu_info()
        if not gpus:
            issues.append("No AMD GPUs detected")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "gpu_count": len(gpus),
            "rocm_path": str(self._rocm_path),
        }
