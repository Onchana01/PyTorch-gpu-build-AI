from typing import Optional, Dict, Any, List, Pattern as RePattern
from dataclasses import dataclass, field
from enum import Enum
import re
from datetime import datetime, timezone

from src.common.config.constants import FailureCategory
from src.common.config.logging_config import get_logger
from src.common.utils.hash_utils import compute_signature


logger = get_logger(__name__)


@dataclass
class FailurePattern:
    pattern_id: str
    name: str
    regex: RePattern
    category: FailureCategory
    severity: int = 5
    description: str = ""
    keywords: List[str] = field(default_factory=list)
    extract_groups: List[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class PatternMatch:
    pattern: FailurePattern
    matched_text: str
    extracted_data: Dict[str, str] = field(default_factory=dict)
    confidence: float = 1.0
    line_number: Optional[int] = None
    context: List[str] = field(default_factory=list)


class PatternMatcher:
    BUILTIN_PATTERNS = [
        FailurePattern(
            pattern_id="hip_runtime_error",
            name="HIP Runtime Error",
            regex=re.compile(r"hip(?:Error|ApiError)_(\w+)"),
            category=FailureCategory.RUNTIME_ERROR,
            severity=8,
            description="HIP API runtime error",
            keywords=["hip", "runtime", "api"],
        ),
        FailurePattern(
            pattern_id="rocm_compiler_error",
            name="ROCm Compiler Error",
            regex=re.compile(r"clang.*error:\s*(.+)"),
            category=FailureCategory.COMPILATION_ERROR,
            severity=7,
            description="ROCm clang compiler error",
        ),
        FailurePattern(
            pattern_id="undefined_symbol",
            name="Undefined Symbol",
            regex=re.compile(r"undefined (?:reference|symbol)[: ]+[`']?(\w+)"),
            category=FailureCategory.LINKER_ERROR,
            severity=7,
            description="Linker cannot find symbol",
            extract_groups=["symbol"],
        ),
        FailurePattern(
            pattern_id="gpu_memory_error",
            name="GPU Memory Error",
            regex=re.compile(r"(?:GPU|device) (?:memory|allocation) (?:error|failed)", re.IGNORECASE),
            category=FailureCategory.GPU_ERROR,
            severity=8,
            description="GPU memory allocation failure",
        ),
        FailurePattern(
            pattern_id="kernel_launch_failed",
            name="Kernel Launch Failed",
            regex=re.compile(r"kernel.*(?:launch|execution).*(?:failed|error)", re.IGNORECASE),
            category=FailureCategory.RUNTIME_ERROR,
            severity=8,
            description="GPU kernel launch failure",
        ),
        FailurePattern(
            pattern_id="cmake_config_error",
            name="CMake Configuration Error",
            regex=re.compile(r"CMake Error.*?:\s*(.+)", re.DOTALL),
            category=FailureCategory.CONFIGURATION_ERROR,
            severity=6,
            description="CMake configuration failed",
        ),
        FailurePattern(
            pattern_id="python_import_error",
            name="Python Import Error",
            regex=re.compile(r"(?:Import|Module)Error:\s*(.+)"),
            category=FailureCategory.DEPENDENCY_ERROR,
            severity=6,
            description="Python module import failure",
        ),
        FailurePattern(
            pattern_id="test_assertion_failed",
            name="Test Assertion Failed",
            regex=re.compile(r"(?:Assertion|Assert).*(?:failed|Error)", re.IGNORECASE),
            category=FailureCategory.TEST_FAILURE,
            severity=5,
            description="Unit test assertion failure",
        ),
        FailurePattern(
            pattern_id="timeout_error",
            name="Timeout Error",
            regex=re.compile(r"(?:timed? ?out|timeout|deadline exceeded)", re.IGNORECASE),
            category=FailureCategory.TIMEOUT,
            severity=6,
            description="Operation timed out",
        ),
        FailurePattern(
            pattern_id="segmentation_fault",
            name="Segmentation Fault",
            regex=re.compile(r"(?:Segmentation fault|SIGSEGV|signal 11)"),
            category=FailureCategory.RUNTIME_ERROR,
            severity=9,
            description="Memory access violation",
        ),
    ]
    
    def __init__(self, custom_patterns: Optional[List[FailurePattern]] = None):
        self._patterns = self.BUILTIN_PATTERNS.copy()
        if custom_patterns:
            self._patterns.extend(custom_patterns)
        self._pattern_stats: Dict[str, Dict[str, int]] = {}
    
    def match(self, text: str, context_lines: int = 3) -> List[PatternMatch]:
        matches: List[PatternMatch] = []
        lines = text.split("\n")
        
        for i, line in enumerate(lines):
            for pattern in self._patterns:
                if not pattern.enabled:
                    continue
                
                regex_match = pattern.regex.search(line)
                if regex_match:
                    extracted = self._extract_groups(regex_match, pattern)
                    
                    start_ctx = max(0, i - context_lines)
                    end_ctx = min(len(lines), i + context_lines + 1)
                    
                    matches.append(PatternMatch(
                        pattern=pattern,
                        matched_text=regex_match.group(0),
                        extracted_data=extracted,
                        confidence=self._calculate_confidence(line, pattern),
                        line_number=i + 1,
                        context=lines[start_ctx:end_ctx],
                    ))
                    
                    self._update_stats(pattern.pattern_id, True)
        
        return matches
    
    def match_first(self, text: str) -> Optional[PatternMatch]:
        matches = self.match(text, context_lines=5)
        if matches:
            return sorted(matches, key=lambda m: m.pattern.severity, reverse=True)[0]
        return None
    
    def _extract_groups(self, match: re.Match, pattern: FailurePattern) -> Dict[str, str]:
        extracted = {}
        for i, group_name in enumerate(pattern.extract_groups):
            try:
                extracted[group_name] = match.group(i + 1)
            except IndexError:
                logger.debug(f"Group {group_name} (index {i+1}) not found in match")
        return extracted
    
    def _calculate_confidence(self, line: str, pattern: FailurePattern) -> float:
        confidence = 0.7
        
        keyword_matches = sum(1 for kw in pattern.keywords if kw.lower() in line.lower())
        if pattern.keywords:
            confidence += 0.2 * (keyword_matches / len(pattern.keywords))
        
        if pattern.category == FailureCategory.COMPILATION_ERROR:
            if ": error:" in line or "error:" in line:
                confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _update_stats(self, pattern_id: str, matched: bool) -> None:
        if pattern_id not in self._pattern_stats:
            self._pattern_stats[pattern_id] = {"matches": 0, "total_checks": 0}
        self._pattern_stats[pattern_id]["total_checks"] += 1
        if matched:
            self._pattern_stats[pattern_id]["matches"] += 1
    
    def add_pattern(self, pattern: FailurePattern) -> None:
        self._patterns.append(pattern)
        logger.info(f"Added pattern: {pattern.name}")
    
    def get_pattern(self, pattern_id: str) -> Optional[FailurePattern]:
        for pattern in self._patterns:
            if pattern.pattern_id == pattern_id:
                return pattern
        return None
    
    def get_statistics(self) -> Dict[str, Any]:
        return {
            "pattern_count": len(self._patterns),
            "enabled_count": sum(1 for p in self._patterns if p.enabled),
            "match_stats": self._pattern_stats,
        }
    
    def generate_signature(self, match: PatternMatch) -> str:
        components = [
            match.pattern.pattern_id,
            match.pattern.category.value,
            match.matched_text[:100],
        ]
        if match.extracted_data:
            components.append(str(sorted(match.extracted_data.items())))
        return compute_signature(*components)
