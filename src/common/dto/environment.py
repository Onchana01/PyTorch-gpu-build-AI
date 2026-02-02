from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID
import hashlib

from pydantic import BaseModel, Field, computed_field

from src.common.dto.base import BaseDTO
from src.common.config.constants import ROCmVersion, GPUArchitecture, CompilerType


class CompilerInfo(BaseModel):
    compiler_type: CompilerType
    version: str
    path: str
    target_triple: Optional[str] = None
    supported_standards: List[str] = Field(default_factory=list)
    default_flags: List[str] = Field(default_factory=list)
    is_available: bool = Field(default=True)

    @computed_field
    @property
    def full_version(self) -> str:
        return f"{self.compiler_type.value}-{self.version}"


class GPUInfo(BaseModel):
    device_id: int
    name: str
    architecture: str
    compute_units: int
    memory_gb: float
    memory_bandwidth_gbps: float
    pcie_bus_id: str
    driver_version: str
    firmware_version: Optional[str] = None
    temperature_celsius: Optional[float] = None
    power_usage_watts: Optional[float] = None
    utilization_percent: Optional[float] = None
    memory_used_gb: Optional[float] = None
    is_healthy: bool = Field(default=True)
    health_status: str = Field(default="OK")

    @computed_field
    @property
    def memory_available_gb(self) -> Optional[float]:
        if self.memory_used_gb is not None:
            return self.memory_gb - self.memory_used_gb
        return None


class ROCmEnvironment(BaseModel):
    version: str
    install_path: str
    hip_version: str
    hip_platform: str = Field(default="amd")
    rocblas_version: Optional[str] = None
    rocfft_version: Optional[str] = None
    miopen_version: Optional[str] = None
    hipblas_version: Optional[str] = None
    rocsolver_version: Optional[str] = None
    rocrand_version: Optional[str] = None
    rccl_version: Optional[str] = None
    device_libraries_path: Optional[str] = None
    llvm_path: Optional[str] = None
    hsa_path: Optional[str] = None
    is_valid: bool = Field(default=True)
    validation_errors: List[str] = Field(default_factory=list)

    def get_component_versions(self) -> Dict[str, Optional[str]]:
        return {
            "rocm": self.version,
            "hip": self.hip_version,
            "rocblas": self.rocblas_version,
            "rocfft": self.rocfft_version,
            "miopen": self.miopen_version,
            "hipblas": self.hipblas_version,
            "rocsolver": self.rocsolver_version,
            "rocrand": self.rocrand_version,
            "rccl": self.rccl_version,
        }


class SystemInfo(BaseModel):
    hostname: str
    os_name: str
    os_version: str
    kernel_version: str
    cpu_model: str
    cpu_cores: int
    cpu_threads: int
    memory_total_gb: float
    memory_available_gb: float
    disk_total_gb: float
    disk_available_gb: float
    python_version: str
    python_path: str
    cmake_version: Optional[str] = None
    make_version: Optional[str] = None
    ninja_version: Optional[str] = None
    git_version: Optional[str] = None
    docker_version: Optional[str] = None
    timezone: str = Field(default="UTC")
    locale: str = Field(default="en_US.UTF-8")

    @computed_field
    @property
    def memory_usage_percent(self) -> float:
        return ((self.memory_total_gb - self.memory_available_gb) / 
                self.memory_total_gb) * 100

    @computed_field
    @property
    def disk_usage_percent(self) -> float:
        return ((self.disk_total_gb - self.disk_available_gb) / 
                self.disk_total_gb) * 100


class EnvironmentVariable(BaseModel):
    name: str
    value: str
    is_sensitive: bool = Field(default=False)
    source: str = Field(default="system")

    def get_display_value(self) -> str:
        if self.is_sensitive:
            return "***REDACTED***"
        return self.value


class EnvironmentSnapshot(BaseDTO):
    build_id: Optional[UUID] = None
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    system: SystemInfo
    rocm: ROCmEnvironment
    gpus: List[GPUInfo] = Field(default_factory=list)
    compilers: List[CompilerInfo] = Field(default_factory=list)
    environment_variables: List[EnvironmentVariable] = Field(default_factory=list)
    python_packages: Dict[str, str] = Field(default_factory=dict)
    cmake_cache: Dict[str, str] = Field(default_factory=dict)
    snapshot_hash: Optional[str] = None

    def compute_hash(self) -> str:
        hash_components = [
            self.rocm.version,
            self.rocm.hip_version,
            self.system.os_version,
            self.system.kernel_version,
        ]
        for gpu in sorted(self.gpus, key=lambda g: g.device_id):
            hash_components.extend([gpu.architecture, gpu.driver_version])
        for compiler in sorted(self.compilers, key=lambda c: c.compiler_type.value):
            hash_components.extend([compiler.compiler_type.value, compiler.version])
        
        hash_string = "|".join(hash_components)
        return hashlib.sha256(hash_string.encode()).hexdigest()[:16]

    def get_primary_gpu(self) -> Optional[GPUInfo]:
        if self.gpus:
            return self.gpus[0]
        return None

    def get_gpu_by_id(self, device_id: int) -> Optional[GPUInfo]:
        for gpu in self.gpus:
            if gpu.device_id == device_id:
                return gpu
        return None

    def get_compiler(self, compiler_type: CompilerType) -> Optional[CompilerInfo]:
        for compiler in self.compilers:
            if compiler.compiler_type == compiler_type:
                return compiler
        return None

    def get_environment_variable(self, name: str) -> Optional[str]:
        for env_var in self.environment_variables:
            if env_var.name == name:
                return env_var.value
        return None

    def validate_for_build(self) -> List[str]:
        errors = []
        
        if not self.rocm.is_valid:
            errors.extend(self.rocm.validation_errors)
        
        if not self.gpus:
            errors.append("No AMD GPUs detected")
        else:
            unhealthy_gpus = [g for g in self.gpus if not g.is_healthy]
            if unhealthy_gpus:
                errors.append(
                    f"Unhealthy GPUs: {[g.device_id for g in unhealthy_gpus]}"
                )
        
        hipcc_found = any(
            c.compiler_type == CompilerType.HIPCC for c in self.compilers
        )
        if not hipcc_found:
            errors.append("hipcc compiler not found")
        
        if self.system.memory_available_gb < 16:
            errors.append(
                f"Insufficient memory: {self.system.memory_available_gb:.1f}GB available"
            )
        
        if self.system.disk_available_gb < 50:
            errors.append(
                f"Insufficient disk space: {self.system.disk_available_gb:.1f}GB available"
            )
        
        return errors


class EnvironmentDiff(BaseModel):
    snapshot_before: UUID
    snapshot_after: UUID
    rocm_version_changed: bool = Field(default=False)
    rocm_version_before: Optional[str] = None
    rocm_version_after: Optional[str] = None
    gpu_changes: List[str] = Field(default_factory=list)
    compiler_changes: List[str] = Field(default_factory=list)
    package_changes: Dict[str, tuple] = Field(default_factory=dict)
    environment_variable_changes: Dict[str, tuple] = Field(default_factory=dict)

    @computed_field
    @property
    def has_significant_changes(self) -> bool:
        return (
            self.rocm_version_changed or
            bool(self.gpu_changes) or
            bool(self.compiler_changes)
        )
