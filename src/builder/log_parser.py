from typing import Optional, Dict, Any, List, Pattern
from dataclasses import dataclass, field
from enum import Enum
import re
from datetime import datetime
from pathlib import Path

from src.common.config.constants import FailureCategory
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


@dataclass
class ParsedLogEntry:
    timestamp: Optional[datetime] = None
    level: LogLevel = LogLevel.INFO
    message: str = ""
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    raw_line: str = ""
    line_index: int = 0


@dataclass
class ErrorPattern:
    name: str
    pattern: Pattern
    category: FailureCategory
    severity: int = 5


@dataclass
class ParsedError:
    pattern_name: str
    category: FailureCategory
    severity: int
    message: str
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)


@dataclass
class LogParseResult:
    total_lines: int = 0
    error_count: int = 0
    warning_count: int = 0
    errors: List[ParsedError] = field(default_factory=list)
    warnings: List[ParsedLogEntry] = field(default_factory=list)


class LogParser:
    DEFAULT_ERROR_PATTERNS = [
        ErrorPattern("compilation_error", re.compile(r"^(.+?):(\d+):(\d+): error: (.+)$"), FailureCategory.COMPILATION, 8),
        ErrorPattern("linker_error", re.compile(r"undefined reference to [`'](.+)'"), FailureCategory.LINKING, 7),
        ErrorPattern("hip_error", re.compile(r"HIP error: (.+?) at (.+?):(\d+)"), FailureCategory.RUNTIME, 8),
        ErrorPattern("cmake_error", re.compile(r"CMake Error"), FailureCategory.CONFIGURATION, 6),
        ErrorPattern("segfault", re.compile(r"Segmentation fault|SIGSEGV"), FailureCategory.RUNTIME, 9),
        ErrorPattern("out_of_memory", re.compile(r"out of memory|OOM", re.IGNORECASE), FailureCategory.INFRASTRUCTURE, 8),
        ErrorPattern("timeout", re.compile(r"timed out|timeout", re.IGNORECASE), FailureCategory.INFRASTRUCTURE, 6),
    ]
    
    WARNING_PATTERN = re.compile(r"warning:", re.IGNORECASE)
    
    def __init__(self, context_lines: int = 5):
        self._error_patterns = self.DEFAULT_ERROR_PATTERNS.copy()
        self._context_lines = context_lines
    
    def parse_file(self, log_path: str) -> LogParseResult:
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                return self.parse_content(f.read())
        except Exception as e:
            logger.error(f"Failed to parse log file {log_path}: {e}")
            return LogParseResult()
    
    def parse_content(self, content: str) -> LogParseResult:
        lines = content.split("\n")
        result = LogParseResult(total_lines=len(lines))
        
        for i, line in enumerate(lines):
            for pattern in self._error_patterns:
                if pattern.pattern.search(line):
                    start_ctx = max(0, i - self._context_lines)
                    end_ctx = min(len(lines), i + self._context_lines + 1)
                    
                    file_match = re.search(r"(\S+\.(cpp|c|h|py|hip)):(\d+)", line)
                    
                    result.errors.append(ParsedError(
                        pattern_name=pattern.name,
                        category=pattern.category,
                        severity=pattern.severity,
                        message=line,
                        source_file=file_match.group(1) if file_match else None,
                        line_number=int(file_match.group(3)) if file_match else None,
                        context_before=lines[start_ctx:i],
                        context_after=lines[i + 1:end_ctx],
                    ))
                    result.error_count += 1
                    break
            
            if self.WARNING_PATTERN.search(line):
                result.warnings.append(ParsedLogEntry(level=LogLevel.WARNING, message=line, line_index=i))
                result.warning_count += 1
        
        return result
    
    def get_error_summary(self, result: LogParseResult) -> Dict[str, Any]:
        category_counts: Dict[str, int] = {}
        for error in result.errors:
            cat = error.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        return {
            "total_errors": result.error_count,
            "total_warnings": result.warning_count,
            "category_counts": category_counts,
            "top_errors": [{"pattern": e.pattern_name, "message": e.message[:200]} for e in result.errors[:10]],
        }
