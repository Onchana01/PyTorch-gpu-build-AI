from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import os
import re
from pathlib import Path
from datetime import datetime, timezone

from src.common.config.constants import ROCmVersion, GPUArchitecture
from src.common.config.logging_config import get_logger
from src.common.exceptions.build_exceptions import CompilationError, ConfigurationError


logger = get_logger(__name__)


class CompilerType(str, Enum):
    HIPCC = "hipcc"
    HIPCC_CLANG = "hipcc_clang"
    AMDCLANG = "amdclang"
    AMDCLANGXX = "amdclang++"
    GCC = "gcc"
    GXX = "g++"


@dataclass
class CompilerConfig:
    compiler_type: CompilerType = CompilerType.HIPCC
    rocm_version: Optional[ROCmVersion] = None
    gpu_architecture: Optional[GPUArchitecture] = None
    optimization_level: str = "-O3"
    debug_info: bool = False
    extra_flags: List[str] = field(default_factory=list)
    include_paths: List[str] = field(default_factory=list)
    library_paths: List[str] = field(default_factory=list)
    libraries: List[str] = field(default_factory=list)
    defines: Dict[str, Optional[str]] = field(default_factory=dict)


@dataclass
class CompilerResult:
    success: bool
    output_file: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    compile_time_seconds: float = 0.0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class CompilerWrapper:
    WARNING_PATTERN = re.compile(r"warning:\s*(.+)")
    ERROR_PATTERN = re.compile(r"error:\s*(.+)")
    
    def __init__(
        self,
        rocm_path: str = "/opt/rocm",
        config: Optional[CompilerConfig] = None,
    ):
        self._rocm_path = Path(rocm_path)
        self._config = config or CompilerConfig()
        self._env = self._setup_environment()
    
    def _setup_environment(self) -> Dict[str, str]:
        env = os.environ.copy()
        
        rocm_path = str(self._rocm_path)
        
        env["ROCM_PATH"] = rocm_path
        env["HIP_PATH"] = f"{rocm_path}/hip"
        env["PATH"] = f"{rocm_path}/bin:{rocm_path}/hip/bin:{env.get('PATH', '')}"
        env["LD_LIBRARY_PATH"] = f"{rocm_path}/lib:{rocm_path}/hip/lib:{env.get('LD_LIBRARY_PATH', '')}"
        
        if self._config.gpu_architecture:
            env["HIP_DEVICE_LIB_PATH"] = f"{rocm_path}/amdgcn/bitcode"
        
        return env
    
    def _get_compiler_path(self) -> str:
        compiler_paths = {
            CompilerType.HIPCC: self._rocm_path / "bin" / "hipcc",
            CompilerType.HIPCC_CLANG: self._rocm_path / "bin" / "hipcc",
            CompilerType.AMDCLANG: self._rocm_path / "llvm" / "bin" / "amdclang",
            CompilerType.AMDCLANGXX: self._rocm_path / "llvm" / "bin" / "amdclang++",
            CompilerType.GCC: Path("/usr/bin/gcc"),
            CompilerType.GXX: Path("/usr/bin/g++"),
        }
        
        path = compiler_paths.get(self._config.compiler_type, self._rocm_path / "bin" / "hipcc")
        return str(path)
    
    def _build_compile_command(
        self,
        source_files: List[str],
        output_file: str,
        additional_flags: Optional[List[str]] = None,
    ) -> List[str]:
        cmd = [self._get_compiler_path()]
        
        cmd.append(self._config.optimization_level)
        
        if self._config.debug_info:
            cmd.append("-g")
        
        if self._config.gpu_architecture:
            arch = self._config.gpu_architecture.value
            cmd.append(f"--offload-arch={arch}")
        
        for path in self._config.include_paths:
            cmd.append(f"-I{path}")
        
        for path in self._config.library_paths:
            cmd.append(f"-L{path}")
        
        for lib in self._config.libraries:
            cmd.append(f"-l{lib}")
        
        for name, value in self._config.defines.items():
            if value is not None:
                cmd.append(f"-D{name}={value}")
            else:
                cmd.append(f"-D{name}")
        
        cmd.extend(self._config.extra_flags)
        
        if additional_flags:
            cmd.extend(additional_flags)
        
        cmd.extend(source_files)
        
        cmd.extend(["-o", output_file])
        
        return cmd
    
    async def compile(
        self,
        source_files: List[str],
        output_file: str,
        additional_flags: Optional[List[str]] = None,
        working_dir: Optional[str] = None,
    ) -> CompilerResult:
        cmd = self._build_compile_command(source_files, output_file, additional_flags)
        
        logger.debug(f"Compile command: {' '.join(cmd)}")
        
        start_time = datetime.now(timezone.utc)
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=working_dir,
                env=self._env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            end_time = datetime.now(timezone.utc)
            compile_time = (end_time - start_time).total_seconds()
            
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
            
            warnings = self._extract_warnings(stderr_str)
            errors = self._extract_errors(stderr_str)
            
            result = CompilerResult(
                success=process.returncode == 0,
                output_file=output_file if process.returncode == 0 else None,
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=process.returncode,
                compile_time_seconds=compile_time,
                warnings=warnings,
                errors=errors,
            )
            
            if not result.success:
                logger.error(f"Compilation failed: {errors}")
            else:
                logger.info(f"Compilation successful in {compile_time:.2f}s, {len(warnings)} warnings")
            
            return result
            
        except Exception as e:
            logger.exception(f"Compilation error: {e}")
            raise CompilationError(
                message=f"Compilation failed: {str(e)}",
                source_file=source_files[0] if source_files else "unknown",
                compiler=self._get_compiler_path(),
                error_output=str(e),
            )
    
    async def compile_and_link(
        self,
        source_files: List[str],
        output_file: str,
        object_files: Optional[List[str]] = None,
        additional_flags: Optional[List[str]] = None,
        working_dir: Optional[str] = None,
    ) -> CompilerResult:
        object_outputs: List[str] = []
        
        for source in source_files:
            obj_file = Path(source).stem + ".o"
            if working_dir:
                obj_file = str(Path(working_dir) / obj_file)
            
            result = await self.compile(
                source_files=[source],
                output_file=obj_file,
                additional_flags=["-c"] + (additional_flags or []),
                working_dir=working_dir,
            )
            
            if not result.success:
                return result
            
            object_outputs.append(obj_file)
        
        if object_files:
            object_outputs.extend(object_files)
        
        link_cmd = [self._get_compiler_path()]
        link_cmd.extend(object_outputs)
        
        for path in self._config.library_paths:
            link_cmd.append(f"-L{path}")
        
        for lib in self._config.libraries:
            link_cmd.append(f"-l{lib}")
        
        link_cmd.extend(["-o", output_file])
        
        logger.debug(f"Link command: {' '.join(link_cmd)}")
        
        start_time = datetime.now(timezone.utc)
        
        process = await asyncio.create_subprocess_exec(
            *link_cmd,
            cwd=working_dir,
            env=self._env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout, stderr = await process.communicate()
        
        end_time = datetime.now(timezone.utc)
        link_time = (end_time - start_time).total_seconds()
        
        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")
        
        return CompilerResult(
            success=process.returncode == 0,
            output_file=output_file if process.returncode == 0 else None,
            stdout=stdout_str,
            stderr=stderr_str,
            exit_code=process.returncode,
            compile_time_seconds=link_time,
            warnings=self._extract_warnings(stderr_str),
            errors=self._extract_errors(stderr_str),
        )
    
    def _extract_warnings(self, output: str) -> List[str]:
        return self.WARNING_PATTERN.findall(output)
    
    def _extract_errors(self, output: str) -> List[str]:
        return self.ERROR_PATTERN.findall(output)
    
    async def get_compiler_version(self) -> Dict[str, str]:
        cmd = [self._get_compiler_path(), "--version"]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=self._env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, _ = await process.communicate()
            version_output = stdout.decode("utf-8", errors="replace")
            
            return {
                "compiler": self._config.compiler_type.value,
                "path": self._get_compiler_path(),
                "version": version_output.split("\n")[0] if version_output else "unknown",
                "full_output": version_output,
            }
        except Exception as e:
            return {
                "compiler": self._config.compiler_type.value,
                "path": self._get_compiler_path(),
                "error": str(e),
            }
    
    async def check_gpu_target_support(self, architecture: GPUArchitecture) -> bool:
        cmd = [self._get_compiler_path(), "--print-targets"]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=self._env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, _ = await process.communicate()
            targets = stdout.decode("utf-8", errors="replace")
            
            return architecture.value in targets
        except Exception:
            return False
    
    def set_config(self, config: CompilerConfig) -> None:
        self._config = config
        self._env = self._setup_environment()
