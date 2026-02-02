from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from src.analyzer.pattern_matcher import PatternMatch
from src.analyzer.root_cause_analyzer import RootCauseResult
from src.common.config.constants import FailureCategory
from src.common.config.logging_config import get_logger
from src.common.dto.fix import FixRecommendation as FixRecommendationDTO


logger = get_logger(__name__)


class RecommendationType(str, Enum):
    CODE_FIX = "code_fix"
    CONFIGURATION = "configuration"
    ENVIRONMENT = "environment"
    DEPENDENCY = "dependency"
    RETRY = "retry"
    MANUAL_INTERVENTION = "manual_intervention"


@dataclass
class FixRecommendation:
    recommendation_id: str
    recommendation_type: RecommendationType
    title: str
    description: str
    priority: int = 5
    steps: List[str] = field(default_factory=list)
    code_snippet: Optional[str] = None
    affected_files: List[str] = field(default_factory=list)
    estimated_time_minutes: int = 30
    confidence: float = 0.7
    auto_applicable: bool = False
    tags: List[str] = field(default_factory=list)


class RecommendationEngine:
    CATEGORY_RECOMMENDATIONS: Dict[FailureCategory, List[FixRecommendation]] = {
        FailureCategory.COMPILATION_ERROR: [
            FixRecommendation(
                recommendation_id="fix_compilation_include",
                recommendation_type=RecommendationType.CODE_FIX,
                title="Fix Missing Include",
                description="Add missing header include to resolve compilation error",
                priority=8,
                steps=["Identify the missing symbol", "Add appropriate #include directive", "Rebuild"],
                estimated_time_minutes=10,
                auto_applicable=False,
            ),
            FixRecommendation(
                recommendation_id="fix_hip_compilation",
                recommendation_type=RecommendationType.CODE_FIX,
                title="Fix HIP Compilation Error",
                description="Correct HIP-specific compilation issues",
                priority=7,
                steps=["Check HIP API compatibility", "Update deprecated APIs", "Verify ROCM_PATH"],
                estimated_time_minutes=30,
            ),
        ],
        FailureCategory.LINKER_ERROR: [
            FixRecommendation(
                recommendation_id="fix_undefined_symbol",
                recommendation_type=RecommendationType.CONFIGURATION,
                title="Fix Undefined Symbol",
                description="Link against required library to resolve undefined symbol",
                priority=7,
                steps=["Identify missing library", "Add to CMakeLists.txt", "Rebuild"],
                estimated_time_minutes=15,
            ),
        ],
        FailureCategory.GPU_ERROR: [
            FixRecommendation(
                recommendation_id="fix_gpu_memory",
                recommendation_type=RecommendationType.ENVIRONMENT,
                title="Fix GPU Memory Issue",
                description="Reduce memory usage or increase GPU resources",
                priority=8,
                steps=["Check GPU memory usage with rocm-smi", "Reduce batch size", "Clear GPU memory"],
                estimated_time_minutes=20,
            ),
            FixRecommendation(
                recommendation_id="verify_rocm_install",
                recommendation_type=RecommendationType.ENVIRONMENT,
                title="Verify ROCm Installation",
                description="Ensure ROCm is properly installed and configured",
                priority=6,
                steps=["Run rocm-smi to verify GPU detection", "Check ROCM_PATH", "Reinstall if needed"],
                estimated_time_minutes=30,
            ),
        ],
        FailureCategory.CONFIGURATION_ERROR: [
            FixRecommendation(
                recommendation_id="fix_cmake_config",
                recommendation_type=RecommendationType.CONFIGURATION,
                title="Fix CMake Configuration",
                description="Correct CMake configuration issues",
                priority=7,
                steps=["Review CMake error message", "Check required dependencies", "Update CMakeLists.txt"],
                estimated_time_minutes=20,
            ),
        ],
        FailureCategory.DEPENDENCY_ERROR: [
            FixRecommendation(
                recommendation_id="install_dependency",
                recommendation_type=RecommendationType.DEPENDENCY,
                title="Install Missing Dependency",
                description="Install required package or library",
                priority=8,
                steps=["Identify missing dependency", "Install using package manager", "Verify installation"],
                estimated_time_minutes=15,
            ),
        ],
        FailureCategory.TIMEOUT: [
            FixRecommendation(
                recommendation_id="increase_timeout",
                recommendation_type=RecommendationType.CONFIGURATION,
                title="Increase Timeout",
                description="Increase build or test timeout limits",
                priority=5,
                steps=["Identify timeout source", "Increase timeout value", "Retry build"],
                estimated_time_minutes=5,
                auto_applicable=True,
            ),
            FixRecommendation(
                recommendation_id="retry_build",
                recommendation_type=RecommendationType.RETRY,
                title="Retry Build",
                description="Retry the build as timeout may be transient",
                priority=6,
                steps=["Trigger build retry"],
                estimated_time_minutes=5,
                auto_applicable=True,
            ),
        ],
    }
    
    def __init__(self, knowledge_base=None):
        self._knowledge_base = knowledge_base
        self._custom_recommendations: Dict[str, List[FixRecommendation]] = {}
    
    def recommend(
        self,
        root_cause: RootCauseResult,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[FixRecommendation]:
        recommendations = []
        
        category_recs = self.CATEGORY_RECOMMENDATIONS.get(root_cause.category, [])
        recommendations.extend(category_recs)
        
        if self._knowledge_base:
            kb_recs = self._knowledge_base.get_recommendations(root_cause.signature)
            recommendations.extend(kb_recs)
        
        pattern_key = root_cause.primary_cause[:50]
        if pattern_key in self._custom_recommendations:
            recommendations.extend(self._custom_recommendations[pattern_key])
        
        recommendations = self._filter_and_rank(recommendations, root_cause, context)
        
        return recommendations[:5]
    
    def _filter_and_rank(
        self,
        recommendations: List[FixRecommendation],
        root_cause: RootCauseResult,
        context: Optional[Dict[str, Any]],
    ) -> List[FixRecommendation]:
        scored = []
        
        for rec in recommendations:
            score = rec.priority * 10
            score += rec.confidence * 20
            
            if rec.auto_applicable:
                score += 15
            
            if context and context.get("retry_count", 0) > 0:
                if rec.recommendation_type == RecommendationType.RETRY:
                    score -= 20
            
            scored.append((rec, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return [rec for rec, _ in scored]
    
    def add_recommendation(
        self,
        pattern_key: str,
        recommendation: FixRecommendation,
    ) -> None:
        if pattern_key not in self._custom_recommendations:
            self._custom_recommendations[pattern_key] = []
        self._custom_recommendations[pattern_key].append(recommendation)
        logger.info(f"Added recommendation for pattern: {pattern_key}")
    
    def learn_from_fix(
        self,
        root_cause: RootCauseResult,
        applied_fix: FixRecommendation,
        success: bool,
    ) -> None:
        if success:
            pattern_key = root_cause.primary_cause[:50]
            improved_rec = FixRecommendation(
                recommendation_id=applied_fix.recommendation_id,
                recommendation_type=applied_fix.recommendation_type,
                title=applied_fix.title,
                description=applied_fix.description,
                priority=min(applied_fix.priority + 1, 10),
                steps=applied_fix.steps,
                confidence=min(applied_fix.confidence + 0.1, 1.0),
            )
            self.add_recommendation(pattern_key, improved_rec)
            logger.info(f"Learned successful fix for: {pattern_key}")
