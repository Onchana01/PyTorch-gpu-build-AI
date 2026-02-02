from typing import List, Dict, Optional, Any

from src.common.dto.failure import FailureRecord
from src.common.dto.fix import FixRecommendation
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class MarkdownFormatter:
    def format_failure(self, failure: FailureRecord, include_full_trace: bool = False) -> str:
        lines = []
        
        lines.append(f"### {failure.category.value}")
        
        if failure.component:
            lines.append(f"**Component:** {failure.component}")
        
        if failure.file_path:
            location = failure.file_path
            if failure.line_number:
                location += f":{failure.line_number}"
            lines.append(f"**Location:** `{location}`")
        
        if failure.error_message:
            message = str(failure.error_message)
            if not include_full_trace and len(message) > 500:
                message = message[:500] + "..."
            lines.append(f"\n```\n{message}\n```")
        
        if failure.signature:
            lines.append(f"\n<sub>Signature: `{failure.signature[:24]}`</sub>")
        
        return "\n".join(lines)

    def format_fix(self, fix: FixRecommendation) -> str:
        lines = []
        
        confidence_bar = self._create_progress_bar(fix.confidence)
        lines.append(f"### {fix.title}")
        lines.append(f"**Confidence:** {confidence_bar} {int(fix.confidence * 100)}%")
        lines.append(f"**Type:** {fix.recommendation_type.value}")
        lines.append(f"**Estimated Time:** {fix.estimated_time_minutes} minutes")
        lines.append(f"\n{fix.description}")
        
        if fix.steps:
            lines.append("\n**Steps:**")
            for i, step in enumerate(fix.steps, 1):
                lines.append(f"{i}. {step}")
        
        if fix.auto_applicable:
            lines.append("\n> ✨ This fix can be applied automatically")
        
        return "\n".join(lines)

    def create_table(
        self,
        headers: List[str],
        rows: List[List[str]],
        alignment: Optional[List[str]] = None,
    ) -> str:
        if not headers:
            return ""
        
        if alignment is None:
            alignment = ["left"] * len(headers)
        
        separator_chars = {
            "left": ":---",
            "center": ":---:",
            "right": "---:",
        }
        
        header_row = "| " + " | ".join(headers) + " |"
        separator_row = "| " + " | ".join(separator_chars.get(a, ":---") for a in alignment) + " |"
        
        data_rows = []
        for row in rows:
            padded_row = row + [""] * (len(headers) - len(row))
            data_rows.append("| " + " | ".join(str(cell) for cell in padded_row) + " |")
        
        return "\n".join([header_row, separator_row] + data_rows)

    def create_collapsible(self, summary: str, content: str) -> str:
        return f"<details>\n<summary>{summary}</summary>\n\n{content}\n</details>"

    def create_code_block(self, code: str, language: str = "") -> str:
        return f"```{language}\n{code}\n```"

    def create_checkbox_list(self, items: List[str], checked: Optional[List[bool]] = None) -> str:
        if checked is None:
            checked = [False] * len(items)
        
        lines = []
        for item, is_checked in zip(items, checked):
            checkbox = "[x]" if is_checked else "[ ]"
            lines.append(f"- {checkbox} {item}")
        
        return "\n".join(lines)

    def create_badge(self, label: str, message: str, color: str = "blue") -> str:
        label_encoded = label.replace(" ", "%20").replace("-", "--")
        message_encoded = message.replace(" ", "%20").replace("-", "--")
        return f"![{label}](https://img.shields.io/badge/{label_encoded}-{message_encoded}-{color})"

    def escape_markdown(self, text: str) -> str:
        special_chars = ["\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", ".", "!", "|"]
        for char in special_chars:
            text = text.replace(char, f"\\{char}")
        return text

    def _create_progress_bar(self, value: float, width: int = 10) -> str:
        filled = int(value * width)
        empty = width - filled
        return "█" * filled + "░" * empty

    def format_failures_summary(self, failures: List[FailureRecord]) -> str:
        if not failures:
            return "No failures detected ✅"
        
        category_counts: Dict[str, int] = {}
        for f in failures:
            cat = f.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        lines = [f"### Failure Summary ({len(failures)} total)"]
        lines.append("")
        
        headers = ["Category", "Count", "Percentage"]
        rows = []
        for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
            pct = count / len(failures) * 100
            rows.append([cat, str(count), f"{pct:.1f}%"])
        
        lines.append(self.create_table(headers, rows))
        
        return "\n".join(lines)
