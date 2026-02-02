from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, status, Query

from src.analyzer.recommendation_engine import RecommendationEngine, FixRecommendation
from src.common.config.constants import FailureCategory
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/fixes")

_recommendation_engine = RecommendationEngine()


@router.get("", response_model=Dict[str, Any])
async def list_fixes(
    category: Optional[str] = Query(None, description="Filter by failure category"),
    limit: int = Query(20, ge=1, le=50),
) -> Dict[str, Any]:
    fixes = []
    
    if category:
        cat = FailureCategory(category)
        cat_fixes = _recommendation_engine.CATEGORY_RECOMMENDATIONS.get(cat, [])
        fixes.extend(cat_fixes)
    else:
        for cat_fixes in _recommendation_engine.CATEGORY_RECOMMENDATIONS.values():
            fixes.extend(cat_fixes)
    
    return {
        "items": [_serialize_fix(f) for f in fixes[:limit]],
        "total": len(fixes),
    }


@router.get("/{fix_id}", response_model=Dict[str, Any])
async def get_fix(fix_id: str) -> Dict[str, Any]:
    for fixes in _recommendation_engine.CATEGORY_RECOMMENDATIONS.values():
        for fix in fixes:
            if fix.recommendation_id == fix_id:
                return _serialize_fix(fix)
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Fix {fix_id} not found",
    )


@router.post("/{fix_id}/feedback", status_code=status.HTTP_200_OK)
async def submit_fix_feedback(
    fix_id: str,
    success: bool,
    comment: Optional[str] = None,
) -> Dict[str, str]:
    logger.info(f"Received feedback for fix {fix_id}: success={success}, comment={comment}")
    
    return {
        "status": "recorded",
        "message": f"Feedback for fix {fix_id} has been recorded",
    }


@router.get("/search", response_model=List[Dict[str, Any]])
async def search_fixes(
    error_signature: Optional[str] = Query(None),
    keywords: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=20),
) -> List[Dict[str, Any]]:
    results = []
    
    for fixes in _recommendation_engine.CATEGORY_RECOMMENDATIONS.values():
        for fix in fixes:
            if keywords and keywords.lower() in fix.title.lower():
                results.append(fix)
            elif keywords and keywords.lower() in fix.description.lower():
                results.append(fix)
    
    return [_serialize_fix(f) for f in results[:limit]]


def _serialize_fix(fix: FixRecommendation) -> Dict[str, Any]:
    return {
        "recommendation_id": fix.recommendation_id,
        "type": fix.recommendation_type.value,
        "title": fix.title,
        "description": fix.description,
        "priority": fix.priority,
        "steps": fix.steps,
        "confidence": fix.confidence,
        "auto_applicable": fix.auto_applicable,
        "estimated_time_minutes": fix.estimated_time_minutes,
    }
