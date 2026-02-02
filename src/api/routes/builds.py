from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Query, Request

from src.storage.database import BuildRepository
from src.common.dto.build import BuildRequest, BuildResult, BuildConfiguration
from src.common.config.constants import BuildStatus, ROCmVersion, GPUArchitecture
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/builds")

_build_repository = BuildRepository()


@router.get("", response_model=Dict[str, Any])
async def list_builds(
    status: Optional[str] = Query(None, description="Filter by build status"),
    branch: Optional[str] = Query(None, description="Filter by branch name"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    filters = {}
    if status:
        filters["status"] = BuildStatus(status)
    
    builds = await _build_repository.list(filters=filters, limit=limit, offset=offset)
    
    return {
        "items": [_serialize_build(b) for b in builds],
        "total": len(builds),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{build_id}", response_model=Dict[str, Any])
async def get_build(build_id: UUID) -> Dict[str, Any]:
    build = await _build_repository.get(build_id)
    
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_id} not found",
        )
    
    return _serialize_build(build)


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def trigger_build(
    request: Request,
    repository: str,
    branch: str = "main",
    commit_sha: Optional[str] = None,
    rocm_version: Optional[str] = None,
    gpu_architecture: Optional[str] = None,
) -> Dict[str, Any]:
    from uuid import uuid4
    
    build_request = BuildRequest(
        id=uuid4(),
        repository=repository,
        branch=branch,
        commit_sha=commit_sha or "HEAD",
        pr_number=None,
        triggered_by=getattr(request.state, "user", {}).get("sub", "api"),
        triggered_at=datetime.now(timezone.utc),
    )
    
    config = BuildConfiguration(
        rocm_version=ROCmVersion(rocm_version) if rocm_version else ROCmVersion.ROCM_6_0,
        gpu_architecture=GPUArchitecture(gpu_architecture) if gpu_architecture else GPUArchitecture.GFX90A,
    )
    
    build_result = BuildResult(
        build_id=uuid4(),
        request=build_request,
        configuration=config,
        status=BuildStatus.PENDING,
        started_at=datetime.now(timezone.utc),
    )
    
    await _build_repository.create(build_result)
    
    logger.info(f"Build triggered: {build_result.build_id} for {repository}@{branch}")
    
    return _serialize_build(build_result)


@router.delete("/{build_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_build(build_id: UUID) -> None:
    build = await _build_repository.get(build_id)
    
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_id} not found",
        )
    
    if build.status not in [BuildStatus.PENDING, BuildStatus.RUNNING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel build in {build.status.value} state",
        )
    
    await _build_repository.update(build_id, {"status": BuildStatus.CANCELLED})
    logger.info(f"Build cancelled: {build_id}")


@router.get("/{build_id}/logs")
async def get_build_logs(build_id: UUID) -> Dict[str, Any]:
    build = await _build_repository.get(build_id)
    
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_id} not found",
        )
    
    return {
        "build_id": str(build_id),
        "logs_url": build.logs_url,
        "log_content": "Build logs would be streamed here...",
    }


def _serialize_build(build: BuildResult) -> Dict[str, Any]:
    return {
        "build_id": str(build.build_id),
        "repository": build.request.repository,
        "branch": build.request.branch,
        "commit_sha": build.request.commit_sha,
        "status": build.status.value,
        "started_at": build.started_at.isoformat() if build.started_at else None,
        "completed_at": build.completed_at.isoformat() if build.completed_at else None,
        "duration_seconds": build.duration_seconds,
        "configuration": {
            "rocm_version": build.configuration.rocm_version.value if build.configuration.rocm_version else None,
            "gpu_architecture": build.configuration.gpu_architecture.value if build.configuration.gpu_architecture else None,
        },
    }
