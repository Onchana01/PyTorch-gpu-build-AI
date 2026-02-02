from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Query

from src.storage.database import FailureRepository
from src.common.dto.failure import FailureRecord
from src.common.config.constants import FailureCategory
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/failures")

_failure_repository = FailureRepository()


@router.get("", response_model=Dict[str, Any])
async def list_failures(
    category: Optional[str] = Query(None, description="Filter by failure category"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    if category:
        failures = await _failure_repository.get_by_category(FailureCategory(category))
    else:
        failures = await _failure_repository.list(limit=limit, offset=offset)
    
    return {
        "items": [_serialize_failure(f) for f in failures],
        "total": len(failures),
        "limit": limit,
        "offset": offset,
    }


@router.get("/common", response_model=List[Dict[str, Any]])
async def get_common_failures(
    limit: int = Query(10, ge=1, le=50),
) -> List[Dict[str, Any]]:
    return await _failure_repository.get_most_common(limit=limit)


@router.get("/{failure_id}", response_model=Dict[str, Any])
async def get_failure(failure_id: UUID) -> Dict[str, Any]:
    failure = await _failure_repository.get(failure_id)
    
    if not failure:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failure {failure_id} not found",
        )
    
    return _serialize_failure(failure)


@router.get("/{failure_id}/similar", response_model=List[Dict[str, Any]])
async def get_similar_failures(failure_id: UUID, limit: int = Query(5, ge=1, le=20)) -> List[Dict[str, Any]]:
    failure = await _failure_repository.get(failure_id)
    
    if not failure:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failure {failure_id} not found",
        )
    
    if failure.signature:
        similar = await _failure_repository.get_by_signature(failure.signature)
        return [_serialize_failure(f) for f in similar[:limit] if f.failure_id != failure_id]
    
    return []


def _serialize_failure(failure: FailureRecord) -> Dict[str, Any]:
    return {
        "failure_id": str(failure.failure_id),
        "build_id": str(failure.build_id) if failure.build_id else None,
        "category": failure.category.value,
        "error_message": str(failure.error_message)[:500] if failure.error_message else None,
        "signature": failure.signature,
        "file_path": failure.file_path,
        "line_number": failure.line_number,
        "created_at": failure.created_at.isoformat() if failure.created_at else None,
    }
