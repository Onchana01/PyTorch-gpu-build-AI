from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
import asyncio
import shutil
import os
from datetime import datetime, timezone

from src.common.dto.build import BuildArtifact
from src.common.config.logging_config import get_logger
from src.common.utils.hash_utils import hash_file
from src.common.utils.file_utils import ensure_directory, get_file_size


logger = get_logger(__name__)


class StorageBackend(str, Enum):
    LOCAL = "local"
    S3 = "s3"
    GCS = "gcs"
    AZURE = "azure"


@dataclass
class StorageConfig:
    backend: StorageBackend = StorageBackend.LOCAL
    base_path: str = "/var/lib/cicd/artifacts"
    bucket_name: Optional[str] = None
    region: Optional[str] = None
    max_artifact_size_mb: int = 1000


class StorageProvider(ABC):
    @abstractmethod
    async def upload(self, local_path: str, remote_path: str) -> str:
        raise NotImplementedError("Subclasses must implement upload method")
    
    @abstractmethod
    async def download(self, remote_path: str, local_path: str) -> bool:
        raise NotImplementedError("Subclasses must implement download method")
    
    @abstractmethod
    async def delete(self, remote_path: str) -> bool:
        raise NotImplementedError("Subclasses must implement delete method")
    
    @abstractmethod
    async def exists(self, remote_path: str) -> bool:
        raise NotImplementedError("Subclasses must implement exists method")
    
    @abstractmethod
    async def get_url(self, remote_path: str, expiry_seconds: int = 3600) -> str:
        raise NotImplementedError("Subclasses must implement get_url method")


class LocalStorageProvider(StorageProvider):
    def __init__(self, base_path: str):
        self._base_path = Path(base_path)
        ensure_directory(self._base_path)
    
    async def upload(self, local_path: str, remote_path: str) -> str:
        dest = self._base_path / remote_path
        ensure_directory(dest.parent)
        
        await asyncio.get_event_loop().run_in_executor(
            None, shutil.copy2, local_path, dest
        )
        
        return str(dest)
    
    async def download(self, remote_path: str, local_path: str) -> bool:
        source = self._base_path / remote_path
        if not source.exists():
            return False
        
        await asyncio.get_event_loop().run_in_executor(
            None, shutil.copy2, source, local_path
        )
        return True
    
    async def delete(self, remote_path: str) -> bool:
        path = self._base_path / remote_path
        if path.exists():
            path.unlink()
            return True
        return False
    
    async def exists(self, remote_path: str) -> bool:
        return (self._base_path / remote_path).exists()
    
    async def get_url(self, remote_path: str, expiry_seconds: int = 3600) -> str:
        return f"file://{self._base_path / remote_path}"


class S3StorageProvider(StorageProvider):
    def __init__(self, bucket_name: str, region: Optional[str] = None):
        self._bucket_name = bucket_name
        self._region = region
        self._client = None
    
    async def initialize(self) -> None:
        try:
            import boto3
            self._client = boto3.client("s3", region_name=self._region)
            logger.info(f"S3 storage provider initialized for bucket: {self._bucket_name}")
        except ImportError:
            logger.error("boto3 not installed")
            raise
    
    async def upload(self, local_path: str, remote_path: str) -> str:
        if not self._client:
            raise RuntimeError("S3 client not initialized")
        
        def _upload():
            self._client.upload_file(local_path, self._bucket_name, remote_path)
        
        await asyncio.get_event_loop().run_in_executor(None, _upload)
        return f"s3://{self._bucket_name}/{remote_path}"
    
    async def download(self, remote_path: str, local_path: str) -> bool:
        if not self._client:
            return False
        
        try:
            def _download():
                self._client.download_file(self._bucket_name, remote_path, local_path)
            
            await asyncio.get_event_loop().run_in_executor(None, _download)
            return True
        except Exception:
            return False
    
    async def delete(self, remote_path: str) -> bool:
        if not self._client:
            return False
        
        try:
            def _delete():
                self._client.delete_object(Bucket=self._bucket_name, Key=remote_path)
            
            await asyncio.get_event_loop().run_in_executor(None, _delete)
            return True
        except Exception:
            return False
    
    async def exists(self, remote_path: str) -> bool:
        if not self._client:
            return False
        
        try:
            def _head():
                self._client.head_object(Bucket=self._bucket_name, Key=remote_path)
            
            await asyncio.get_event_loop().run_in_executor(None, _head)
            return True
        except Exception:
            return False
    
    async def get_url(self, remote_path: str, expiry_seconds: int = 3600) -> str:
        if not self._client:
            return ""
        
        def _presign():
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket_name, "Key": remote_path},
                ExpiresIn=expiry_seconds,
            )
        
        return await asyncio.get_event_loop().run_in_executor(None, _presign)


class ArtifactStorage:
    def __init__(self, config: Optional[StorageConfig] = None):
        self._config = config or StorageConfig()
        self._provider: Optional[StorageProvider] = None
    
    async def initialize(self) -> None:
        if self._config.backend == StorageBackend.LOCAL:
            self._provider = LocalStorageProvider(self._config.base_path)
        elif self._config.backend == StorageBackend.S3:
            provider = S3StorageProvider(self._config.bucket_name, self._config.region)
            await provider.initialize()
            self._provider = provider
        else:
            self._provider = LocalStorageProvider(self._config.base_path)
        
        logger.info(f"Artifact storage initialized with backend: {self._config.backend.value}")
    
    async def store_artifact(
        self,
        artifact: BuildArtifact,
        build_id: str,
    ) -> str:
        size_mb = artifact.size_bytes / (1024 * 1024)
        if size_mb > self._config.max_artifact_size_mb:
            raise ValueError(f"Artifact size {size_mb:.1f}MB exceeds limit")
        
        remote_path = f"{build_id}/{artifact.name}"
        
        url = await self._provider.upload(artifact.path, remote_path)
        logger.info(f"Stored artifact: {artifact.name} -> {url}")
        
        return url
    
    async def retrieve_artifact(
        self,
        remote_path: str,
        local_path: str,
    ) -> bool:
        return await self._provider.download(remote_path, local_path)
    
    async def delete_artifact(self, remote_path: str) -> bool:
        return await self._provider.delete(remote_path)
    
    async def get_download_url(
        self,
        remote_path: str,
        expiry_seconds: int = 3600,
    ) -> str:
        return await self._provider.get_url(remote_path, expiry_seconds)
    
    async def cleanup_old_artifacts(
        self,
        build_id: str,
        max_age_days: int = 30,
    ) -> int:
        if self._config.backend == StorageBackend.LOCAL:
            build_dir = Path(self._config.base_path) / build_id
            if not build_dir.exists():
                return 0
            
            removed = 0
            now = datetime.now(timezone.utc)
            
            for item in build_dir.rglob("*"):
                if item.is_file():
                    mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                    if (now - mtime).days > max_age_days:
                        item.unlink()
                        removed += 1
            
            return removed
        return 0
