from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import os
import hashlib
import shutil
import tarfile
import gzip
from pathlib import Path
from datetime import datetime, timezone

from src.common.dto.build import BuildArtifact
from src.common.config.logging_config import get_logger
from src.common.utils.hash_utils import hash_file
from src.common.utils.file_utils import get_file_size, ensure_directory


logger = get_logger(__name__)


class ArtifactType(str, Enum):
    BINARY = "binary"
    LIBRARY = "library"
    LOG = "log"
    TEST_RESULT = "test_result"
    COVERAGE = "coverage"
    WHEEL = "wheel"
    TARBALL = "tarball"
    CONFIG = "config"
    OTHER = "other"


@dataclass
class ArtifactSpec:
    pattern: str
    artifact_type: ArtifactType
    compress: bool = False
    retain_days: int = 30


@dataclass
class CollectionConfig:
    artifact_specs: List[ArtifactSpec] = field(default_factory=list)
    output_dir: str = ""
    compress_logs: bool = True
    max_artifact_size_mb: int = 500
    include_build_info: bool = True


class ArtifactCollector:
    DEFAULT_SPECS = [
        ArtifactSpec("*.log", ArtifactType.LOG, compress=True),
        ArtifactSpec("*.whl", ArtifactType.WHEEL),
        ArtifactSpec("*.so", ArtifactType.LIBRARY),
        ArtifactSpec("*.a", ArtifactType.LIBRARY),
        ArtifactSpec("test-results*.xml", ArtifactType.TEST_RESULT),
        ArtifactSpec("coverage*.xml", ArtifactType.COVERAGE),
        ArtifactSpec("*.tar.gz", ArtifactType.TARBALL),
    ]
    
    def __init__(
        self,
        config: Optional[CollectionConfig] = None,
    ):
        self._config = config or CollectionConfig(
            artifact_specs=self.DEFAULT_SPECS
        )
    
    async def collect(
        self,
        context: Any,
    ) -> List[BuildArtifact]:
        artifacts: List[BuildArtifact] = []
        
        output_dir = Path(self._config.output_dir or context.artifact_dir)
        ensure_directory(output_dir)
        
        search_dirs = [
            context.build_dir,
            context.logs_dir,
            context.source_dir,
        ]
        
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            
            dir_artifacts = await self._collect_from_directory(
                search_dir,
                output_dir,
            )
            artifacts.extend(dir_artifacts)
        
        if self._config.include_build_info:
            build_info_artifact = await self._create_build_info_artifact(
                context,
                output_dir,
            )
            if build_info_artifact:
                artifacts.append(build_info_artifact)
        
        logger.info(f"Collected {len(artifacts)} artifacts")
        return artifacts
    
    async def _collect_from_directory(
        self,
        search_dir: Path,
        output_dir: Path,
    ) -> List[BuildArtifact]:
        artifacts: List[BuildArtifact] = []
        
        for spec in self._config.artifact_specs:
            pattern = spec.pattern
            matching_files = list(search_dir.rglob(pattern))
            
            for file_path in matching_files:
                if not file_path.is_file():
                    continue
                
                size_mb = get_file_size(str(file_path)) / (1024 * 1024)
                if size_mb > self._config.max_artifact_size_mb:
                    logger.warning(
                        f"Skipping artifact {file_path}: size {size_mb:.1f}MB exceeds limit"
                    )
                    continue
                
                artifact = await self._process_artifact(
                    file_path,
                    output_dir,
                    spec,
                )
                if artifact:
                    artifacts.append(artifact)
        
        return artifacts
    
    async def _process_artifact(
        self,
        source_path: Path,
        output_dir: Path,
        spec: ArtifactSpec,
    ) -> Optional[BuildArtifact]:
        try:
            dest_name = source_path.name
            
            if spec.compress and not source_path.suffix == ".gz":
                dest_name = f"{dest_name}.gz"
                dest_path = output_dir / dest_name
                await self._compress_file(source_path, dest_path)
            else:
                dest_path = output_dir / dest_name
                if source_path != dest_path:
                    shutil.copy2(source_path, dest_path)
            
            checksum = hash_file(str(dest_path))
            size = get_file_size(str(dest_path))
            
            return BuildArtifact(
                name=dest_name,
                path=str(dest_path),
                artifact_type=spec.artifact_type.value,
                size_bytes=size,
                checksum=checksum,
                created_at=datetime.now(timezone.utc),
                metadata={
                    "original_path": str(source_path),
                    "compressed": spec.compress and not source_path.suffix == ".gz",
                    "retain_days": spec.retain_days,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to process artifact {source_path}: {e}")
            return None
    
    async def _compress_file(
        self,
        source: Path,
        dest: Path,
    ) -> None:
        def _do_compress():
            with open(source, "rb") as f_in:
                with gzip.open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        
        await asyncio.get_event_loop().run_in_executor(None, _do_compress)
    
    async def _create_build_info_artifact(
        self,
        context: Any,
        output_dir: Path,
    ) -> Optional[BuildArtifact]:
        import json
        
        try:
            build_info = {
                "build_id": str(context.build_id),
                "repository": context.request.repository,
                "commit_sha": context.request.commit_sha,
                "branch": context.request.branch,
                "started_at": context.started_at.isoformat() if context.started_at else None,
                "configuration": {
                    "rocm_version": context.configuration.rocm_version.value if context.configuration.rocm_version else None,
                    "gpu_architecture": context.configuration.gpu_architecture.value if context.configuration.gpu_architecture else None,
                    "build_type": context.configuration.build_type,
                    "python_version": context.configuration.python_version,
                },
                "phases_completed": list(context.phase_outputs.keys()),
            }
            
            info_path = output_dir / "build-info.json"
            with open(info_path, "w") as f:
                json.dump(build_info, f, indent=2)
            
            return BuildArtifact(
                name="build-info.json",
                path=str(info_path),
                artifact_type=ArtifactType.CONFIG.value,
                size_bytes=get_file_size(str(info_path)),
                checksum=hash_file(str(info_path)),
                created_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.warning(f"Failed to create build info artifact: {e}")
            return None
    
    async def create_tarball(
        self,
        source_dir: Path,
        output_path: Path,
        exclude_patterns: Optional[List[str]] = None,
    ) -> Optional[BuildArtifact]:
        exclude = exclude_patterns or [".git", "__pycache__", "*.pyc"]
        
        def should_exclude(path: str) -> bool:
            for pattern in exclude:
                if pattern.startswith("*"):
                    if path.endswith(pattern[1:]):
                        return True
                elif pattern in path:
                    return True
            return False
        
        try:
            def _create_tar():
                with tarfile.open(output_path, "w:gz") as tar:
                    for item in source_dir.rglob("*"):
                        if item.is_file() and not should_exclude(str(item)):
                            arcname = item.relative_to(source_dir)
                            tar.add(item, arcname=arcname)
            
            await asyncio.get_event_loop().run_in_executor(None, _create_tar)
            
            return BuildArtifact(
                name=output_path.name,
                path=str(output_path),
                artifact_type=ArtifactType.TARBALL.value,
                size_bytes=get_file_size(str(output_path)),
                checksum=hash_file(str(output_path)),
                created_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(f"Failed to create tarball: {e}")
            return None
    
    async def upload_artifacts(
        self,
        artifacts: List[BuildArtifact],
        destination: str,
    ) -> Dict[str, str]:
        uploaded: Dict[str, str] = {}
        
        for artifact in artifacts:
            try:
                remote_path = f"{destination}/{artifact.name}"
                uploaded[artifact.name] = remote_path
                logger.debug(f"Would upload {artifact.path} to {remote_path}")
            except Exception as e:
                logger.warning(f"Failed to upload artifact {artifact.name}: {e}")
        
        return uploaded
    
    async def cleanup_old_artifacts(
        self,
        artifact_dir: Path,
        max_age_days: int = 30,
    ) -> int:
        removed_count = 0
        now = datetime.now(timezone.utc)
        
        for item in artifact_dir.rglob("*"):
            if not item.is_file():
                continue
            
            try:
                mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                age_days = (now - mtime).days
                
                if age_days > max_age_days:
                    item.unlink()
                    removed_count += 1
            except Exception as e:
                logger.warning(f"Failed to check/remove artifact {item}: {e}")
        
        logger.info(f"Cleaned up {removed_count} old artifacts")
        return removed_count
