from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4
from enum import Enum
import asyncio
import subprocess
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.common.dto.build import BuildRequest, BuildResult, BuildConfiguration, BuildArtifact
from src.common.dto.environment import EnvironmentSnapshot, ROCmEnvironment
from src.common.config.constants import BuildStatus, ROCmVersion, GPUArchitecture
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger
from src.common.exceptions.build_exceptions import (
    BuildFailedException,
    BuildTimeoutException,
    ConfigurationError,
    EnvironmentError,
)
from src.common.utils.time_utils import utc_now, Timer


logger = get_logger(__name__)


class BuildPhase(str, Enum):
    SETUP = "setup"
    CLONE = "clone"
    CONFIGURE = "configure"
    COMPILE = "compile"
    TEST = "test"
    PACKAGE = "package"
    CLEANUP = "cleanup"


@dataclass
class BuildExecutionContext:
    build_id: UUID
    request: BuildRequest
    configuration: BuildConfiguration
    work_dir: Path
    source_dir: Path
    build_dir: Path
    artifact_dir: Path
    logs_dir: Path
    environment: Dict[str, str] = field(default_factory=dict)
    current_phase: BuildPhase = BuildPhase.SETUP
    phase_outputs: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    
    def get_phase_log_path(self, phase: BuildPhase) -> Path:
        return self.logs_dir / f"{phase.value}.log"


class BuildExecutor:
    def __init__(
        self,
        base_work_dir: str = "/tmp/rocm-builds",
        max_build_time_seconds: int = 7200,
    ):
        self._base_work_dir = Path(base_work_dir)
        self._max_build_time = max_build_time_seconds
        self._settings = get_settings()
        self._active_builds: Dict[UUID, BuildExecutionContext] = {}
        self._phase_handlers: Dict[BuildPhase, Callable] = {
            BuildPhase.SETUP: self._execute_setup,
            BuildPhase.CLONE: self._execute_clone,
            BuildPhase.CONFIGURE: self._execute_configure,
            BuildPhase.COMPILE: self._execute_compile,
            BuildPhase.TEST: self._execute_test,
            BuildPhase.PACKAGE: self._execute_package,
            BuildPhase.CLEANUP: self._execute_cleanup,
        }
    
    async def execute_build(
        self,
        request: BuildRequest,
        configuration: BuildConfiguration,
    ) -> BuildResult:
        build_id = request.id
        context = await self._create_context(request, configuration)
        
        self._active_builds[build_id] = context
        timer = Timer()
        timer.start()
        
        status = BuildStatus.SUCCESS
        error_message: Optional[str] = None
        artifacts: List[BuildArtifact] = []
        
        try:
            for phase in BuildPhase:
                if phase == BuildPhase.CLEANUP:
                    continue
                
                context.current_phase = phase
                logger.info(f"Build {build_id}: Starting phase {phase.value}")
                
                try:
                    await asyncio.wait_for(
                        self._execute_phase(context, phase),
                        timeout=self._get_phase_timeout(phase)
                    )
                except asyncio.TimeoutError:
                    raise BuildTimeoutException(
                        message=f"Phase {phase.value} timed out",
                        build_id=str(build_id),
                        phase=phase.value,
                        timeout_seconds=self._get_phase_timeout(phase),
                    )
            
            artifacts = await self._collect_artifacts(context)
            
        except BuildFailedException as e:
            status = BuildStatus.FAILED
            error_message = str(e)
            logger.error(f"Build {build_id} failed: {error_message}")
        except BuildTimeoutException as e:
            status = BuildStatus.TIMEOUT
            error_message = str(e)
            logger.error(f"Build {build_id} timed out: {error_message}")
        except Exception as e:
            status = BuildStatus.FAILED
            error_message = f"Unexpected error: {str(e)}"
            logger.exception(f"Build {build_id} failed with unexpected error")
        finally:
            timer.stop()
            
            try:
                await self._execute_phase(context, BuildPhase.CLEANUP)
            except Exception as e:
                logger.warning(f"Cleanup failed for build {build_id}: {e}")
            
            self._active_builds.pop(build_id, None)
        
        environment_snapshot = await self._capture_environment(context)
        
        return BuildResult(
            build_id=build_id,
            request=request,
            configuration=configuration,
            status=status,
            started_at=context.started_at,
            completed_at=utc_now(),
            duration_seconds=timer.elapsed_seconds,
            environment=environment_snapshot,
            artifacts=artifacts,
            error_message=error_message,
            logs_url=str(context.logs_dir),
        )
    
    async def _create_context(
        self,
        request: BuildRequest,
        configuration: BuildConfiguration,
    ) -> BuildExecutionContext:
        build_id = request.id
        work_dir = self._base_work_dir / str(build_id)
        
        context = BuildExecutionContext(
            build_id=build_id,
            request=request,
            configuration=configuration,
            work_dir=work_dir,
            source_dir=work_dir / "source",
            build_dir=work_dir / "build",
            artifact_dir=work_dir / "artifacts",
            logs_dir=work_dir / "logs",
            started_at=utc_now(),
        )
        
        return context
    
    async def _execute_phase(
        self,
        context: BuildExecutionContext,
        phase: BuildPhase,
    ) -> None:
        handler = self._phase_handlers.get(phase)
        if handler:
            await handler(context)
    
    async def _execute_setup(self, context: BuildExecutionContext) -> None:
        logger.debug(f"Setting up build directories for {context.build_id}")
        
        for directory in [context.work_dir, context.source_dir, context.build_dir,
                          context.artifact_dir, context.logs_dir]:
            directory.mkdir(parents=True, exist_ok=True)
        
        context.environment = await self._setup_environment(context)
        
        context.phase_outputs["setup"] = {
            "work_dir": str(context.work_dir),
            "environment_vars": len(context.environment),
        }
    
    async def _execute_clone(self, context: BuildExecutionContext) -> None:
        logger.debug(f"Cloning repository for {context.build_id}")
        
        repo_url = self._get_repository_url(context.request.repository)
        
        clone_cmd = [
            "git", "clone",
            "--depth", "1",
            "--single-branch",
            "--branch", context.request.branch,
            repo_url,
            str(context.source_dir),
        ]
        
        await self._run_command(
            clone_cmd,
            cwd=str(context.work_dir),
            env=context.environment,
            log_path=context.get_phase_log_path(BuildPhase.CLONE),
        )
        
        checkout_cmd = ["git", "checkout", context.request.commit_sha]
        await self._run_command(
            checkout_cmd,
            cwd=str(context.source_dir),
            env=context.environment,
            log_path=context.get_phase_log_path(BuildPhase.CLONE),
            append_log=True,
        )
        
        context.phase_outputs["clone"] = {
            "repository": context.request.repository,
            "commit": context.request.commit_sha,
        }
    
    async def _execute_configure(self, context: BuildExecutionContext) -> None:
        logger.debug(f"Configuring build for {context.build_id}")
        
        cmake_args = self._build_cmake_args(context)
        
        configure_cmd = [
            "cmake",
            "-B", str(context.build_dir),
            "-S", str(context.source_dir),
            *cmake_args,
        ]
        
        await self._run_command(
            configure_cmd,
            cwd=str(context.source_dir),
            env=context.environment,
            log_path=context.get_phase_log_path(BuildPhase.CONFIGURE),
        )
        
        context.phase_outputs["configure"] = {
            "cmake_args": cmake_args,
        }
    
    async def _execute_compile(self, context: BuildExecutionContext) -> None:
        logger.debug(f"Compiling build for {context.build_id}")
        
        cpu_count = os.cpu_count() or 4
        parallel_jobs = context.configuration.cpu_cores or max(1, cpu_count - 1)
        
        build_cmd = [
            "cmake",
            "--build", str(context.build_dir),
            "--parallel", str(parallel_jobs),
        ]
        
        if context.configuration.build_type:
            build_cmd.extend(["--config", context.configuration.build_type])
        
        await self._run_command(
            build_cmd,
            cwd=str(context.build_dir),
            env=context.environment,
            log_path=context.get_phase_log_path(BuildPhase.COMPILE),
        )
        
        context.phase_outputs["compile"] = {
            "parallel_jobs": parallel_jobs,
        }
    
    async def _execute_test(self, context: BuildExecutionContext) -> None:
        logger.debug(f"Running tests for {context.build_id}")
        
        if context.configuration.skip_tests:
            logger.info(f"Skipping tests for build {context.build_id}")
            context.phase_outputs["test"] = {"skipped": True}
            return
        
        test_cmd = [
            "ctest",
            "--test-dir", str(context.build_dir),
            "--output-on-failure",
            "--parallel", str(context.configuration.cpu_cores or 4),
        ]
        
        try:
            await self._run_command(
                test_cmd,
                cwd=str(context.build_dir),
                env=context.environment,
                log_path=context.get_phase_log_path(BuildPhase.TEST),
            )
            context.phase_outputs["test"] = {"passed": True}
        except BuildFailedException as e:
            context.phase_outputs["test"] = {"passed": False, "error": str(e)}
            raise
    
    async def _execute_package(self, context: BuildExecutionContext) -> None:
        logger.debug(f"Packaging artifacts for {context.build_id}")
        
        for log_file in context.logs_dir.glob("*.log"):
            shutil.copy(log_file, context.artifact_dir / log_file.name)
        
        context.phase_outputs["package"] = {
            "artifact_dir": str(context.artifact_dir),
        }
    
    async def _execute_cleanup(self, context: BuildExecutionContext) -> None:
        logger.debug(f"Cleaning up build {context.build_id}")
        
        for directory in [context.source_dir, context.build_dir]:
            if directory.exists():
                try:
                    shutil.rmtree(directory, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Failed to remove {directory}: {e}")
    
    async def _setup_environment(
        self,
        context: BuildExecutionContext,
    ) -> Dict[str, str]:
        env = os.environ.copy()
        
        config = context.configuration
        rocm_path = f"/opt/rocm-{config.rocm_version.value}" if config.rocm_version else "/opt/rocm"
        
        env["ROCM_PATH"] = rocm_path
        env["HIP_PATH"] = f"{rocm_path}/hip"
        env["PATH"] = f"{rocm_path}/bin:{rocm_path}/hip/bin:{env.get('PATH', '')}"
        env["LD_LIBRARY_PATH"] = f"{rocm_path}/lib:{rocm_path}/hip/lib:{env.get('LD_LIBRARY_PATH', '')}"
        
        if config.gpu_architecture:
            env["HIP_VISIBLE_DEVICES"] = "0"
            env["GPU_DEVICE_ORDINAL"] = "0"
            env["PYTORCH_ROCM_ARCH"] = config.gpu_architecture.value
        
        env["CMAKE_PREFIX_PATH"] = f"{rocm_path}:{env.get('CMAKE_PREFIX_PATH', '')}"
        env["CMAKE_BUILD_TYPE"] = config.build_type or "Release"
        
        if config.extra_env_vars:
            env.update(config.extra_env_vars)
        
        return env
    
    def _build_cmake_args(self, context: BuildExecutionContext) -> List[str]:
        config = context.configuration
        args = []
        
        args.append(f"-DCMAKE_BUILD_TYPE={config.build_type or 'Release'}")
        
        args.append("-DUSE_ROCM=ON")
        args.append("-DUSE_CUDA=OFF")
        
        if config.gpu_architecture:
            args.append(f"-DPYTORCH_ROCM_ARCH={config.gpu_architecture.value}")
        
        if config.rocm_version:
            rocm_path = f"/opt/rocm-{config.rocm_version.value}"
            args.append(f"-DROCM_PATH={rocm_path}")
            args.append(f"-DCMAKE_PREFIX_PATH={rocm_path}")
        
        if config.python_version:
            args.append(f"-DPYTHON_EXECUTABLE=python{config.python_version}")
        
        if config.extra_cmake_args:
            args.extend(config.extra_cmake_args)
        
        return args
    
    def _get_repository_url(self, repository: str) -> str:
        if self._settings.github_token:
            token = self._settings.github_token.get_secret_value()
            return f"https://x-access-token:{token}@github.com/{repository}.git"
        return f"https://github.com/{repository}.git"
    
    async def _run_command(
        self,
        cmd: List[str],
        cwd: str,
        env: Dict[str, str],
        log_path: Path,
        timeout: Optional[int] = None,
        append_log: bool = False,
    ) -> str:
        logger.debug(f"Running command: {' '.join(cmd)}")
        
        mode = "ab" if append_log else "wb"
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        
        output_lines: List[bytes] = []
        
        with open(log_path, mode) as log_file:
            while True:
                try:
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=60
                    )
                except asyncio.TimeoutError:
                    continue
                
                if not line:
                    break
                
                output_lines.append(line)
                log_file.write(line)
                log_file.flush()
        
        await process.wait()
        
        if process.returncode != 0:
            output = b"".join(output_lines).decode("utf-8", errors="replace")
            raise BuildFailedException(
                message=f"Command failed with exit code {process.returncode}",
                build_id=str(self._active_builds.get(list(self._active_builds.keys())[0] if self._active_builds else uuid4()).build_id),
                phase=str(cmd[0]),
                exit_code=process.returncode,
                error_output=output[-4000:],
            )
        
        return b"".join(output_lines).decode("utf-8", errors="replace")
    
    async def _collect_artifacts(
        self,
        context: BuildExecutionContext,
    ) -> List[BuildArtifact]:
        from src.builder.artifact_collector import ArtifactCollector
        
        collector = ArtifactCollector()
        return await collector.collect(context)
    
    async def _capture_environment(
        self,
        context: BuildExecutionContext,
    ) -> Optional[EnvironmentSnapshot]:
        from src.builder.environment_manager import EnvironmentManager
        
        manager = EnvironmentManager()
        return await manager.capture_snapshot()
    
    def _get_phase_timeout(self, phase: BuildPhase) -> int:
        timeouts = {
            BuildPhase.SETUP: 60,
            BuildPhase.CLONE: 300,
            BuildPhase.CONFIGURE: 600,
            BuildPhase.COMPILE: 7200,
            BuildPhase.TEST: 3600,
            BuildPhase.PACKAGE: 300,
            BuildPhase.CLEANUP: 60,
        }
        return timeouts.get(phase, 600)
    
    async def cancel_build(self, build_id: UUID) -> bool:
        if build_id not in self._active_builds:
            return False
        
        logger.info(f"Cancelling build {build_id}")
        return True
    
    def get_active_builds(self) -> List[UUID]:
        return list(self._active_builds.keys())
