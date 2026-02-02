from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from src.analyzer.pattern_matcher import PatternMatcher, PatternMatch
from src.analyzer.similarity_scorer import SimilarityScorer
from src.common.config.constants import FailureCategory
from src.common.config.logging_config import get_logger
from src.common.dto.failure import FailureRecord, RootCauseAnalysis
from src.common.utils.hash_utils import compute_signature


logger = get_logger(__name__)


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"


@dataclass
class RootCauseResult:
    category: FailureCategory
    confidence: ConfidenceLevel
    confidence_score: float
    primary_cause: str
    secondary_causes: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    affected_components: List[str] = field(default_factory=list)
    signature: str = ""
    similar_failures: List[str] = field(default_factory=list)
    analysis_duration_ms: float = 0.0


class RootCauseAnalyzer:
    def __init__(
        self,
        pattern_matcher: Optional[PatternMatcher] = None,
        similarity_scorer: Optional[SimilarityScorer] = None,
    ):
        self._pattern_matcher = pattern_matcher or PatternMatcher()
        self._similarity_scorer = similarity_scorer or SimilarityScorer()
        self._historical_failures: Dict[str, FailureRecord] = {}
    
    def analyze(
        self,
        log_content: str,
        build_context: Optional[Dict[str, Any]] = None,
    ) -> RootCauseResult:
        start_time = datetime.now(timezone.utc)
        
        matches = self._pattern_matcher.match(log_content)
        
        if not matches:
            return RootCauseResult(
                category=FailureCategory.UNKNOWN,
                confidence=ConfidenceLevel.UNCERTAIN,
                confidence_score=0.0,
                primary_cause="No recognizable failure pattern detected",
                analysis_duration_ms=self._elapsed_ms(start_time),
            )
        
        primary_match = self._select_primary_match(matches)
        
        category = primary_match.pattern.category
        primary_cause = self._format_primary_cause(primary_match)
        secondary_causes = self._extract_secondary_causes(matches, primary_match)
        
        evidence = self._collect_evidence(matches)
        affected_components = self._identify_components(matches, build_context)
        
        confidence_score = self._calculate_confidence(matches, primary_match)
        confidence_level = self._score_to_level(confidence_score)
        
        signature = self._generate_signature(primary_match, category)
        similar = self._find_similar_failures(signature, log_content)
        
        return RootCauseResult(
            category=category,
            confidence=confidence_level,
            confidence_score=confidence_score,
            primary_cause=primary_cause,
            secondary_causes=secondary_causes,
            evidence=evidence,
            affected_components=affected_components,
            signature=signature,
            similar_failures=similar,
            analysis_duration_ms=self._elapsed_ms(start_time),
        )
    
    def _select_primary_match(self, matches: List[PatternMatch]) -> PatternMatch:
        return max(matches, key=lambda m: (m.pattern.severity, m.confidence))
    
    def _format_primary_cause(self, match: PatternMatch) -> str:
        cause = f"{match.pattern.name}: {match.matched_text}"
        if match.extracted_data:
            details = ", ".join(f"{k}={v}" for k, v in match.extracted_data.items())
            cause += f" ({details})"
        return cause
    
    def _extract_secondary_causes(
        self,
        matches: List[PatternMatch],
        primary: PatternMatch,
    ) -> List[str]:
        secondary = []
        for match in matches:
            if match is not primary:
                secondary.append(f"{match.pattern.name}: {match.matched_text[:100]}")
        return secondary[:5]
    
    def _collect_evidence(self, matches: List[PatternMatch]) -> List[str]:
        evidence = []
        for match in matches[:10]:
            if match.context:
                evidence.append(f"Line {match.line_number}: {match.matched_text[:150]}")
        return evidence
    
    def _identify_components(
        self,
        matches: List[PatternMatch],
        context: Optional[Dict[str, Any]],
    ) -> List[str]:
        components = set()
        
        for match in matches:
            if match.extracted_data.get("file"):
                components.add(match.extracted_data["file"])
            
            cat = match.pattern.category
            if cat == FailureCategory.COMPILATION_ERROR:
                components.add("compiler")
            elif cat == FailureCategory.LINKER_ERROR:
                components.add("linker")
            elif cat == FailureCategory.GPU_ERROR:
                components.add("gpu_runtime")
            elif cat == FailureCategory.CONFIGURATION_ERROR:
                components.add("cmake")
        
        return list(components)[:10]
    
    def _calculate_confidence(
        self,
        matches: List[PatternMatch],
        primary: PatternMatch,
    ) -> float:
        base_confidence = primary.confidence
        
        if len(matches) > 1:
            same_category = sum(1 for m in matches if m.pattern.category == primary.pattern.category)
            base_confidence += 0.1 * min(same_category / len(matches), 0.3)
        
        severity_boost = primary.pattern.severity / 10 * 0.1
        base_confidence += severity_boost
        
        return min(base_confidence, 1.0)
    
    def _score_to_level(self, score: float) -> ConfidenceLevel:
        if score >= 0.85:
            return ConfidenceLevel.HIGH
        elif score >= 0.65:
            return ConfidenceLevel.MEDIUM
        elif score >= 0.4:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.UNCERTAIN
    
    def _generate_signature(self, match: PatternMatch, category: FailureCategory) -> str:
        return compute_signature(
            category.value,
            match.pattern.pattern_id,
            match.matched_text[:50],
        )
    
    def _find_similar_failures(self, signature: str, log_content: str) -> List[str]:
        similar = []
        
        if signature in self._historical_failures:
            similar.append(str(self._historical_failures[signature].failure_id))
        
        for sig, failure in list(self._historical_failures.items())[:100]:
            score = self._similarity_scorer.score(log_content[:1000], str(failure.error_message)[:1000])
            if score > 0.7:
                similar.append(str(failure.failure_id))
        
        return similar[:5]
    
    def record_failure(self, failure: FailureRecord) -> None:
        if failure.signature:
            self._historical_failures[failure.signature] = failure
    
    def _elapsed_ms(self, start: datetime) -> float:
        return (datetime.now(timezone.utc) - start).total_seconds() * 1000
