from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import aiohttp
from datetime import datetime, timezone

from src.common.dto.build import BuildResult
from src.common.dto.failure import FailureRecord
from src.common.config.constants import BuildStatus
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


@dataclass
class PRCommentPayload:
    repository: str
    pr_number: int
    body: str
    comment_id: Optional[int] = None


class GitHubNotifier:
    API_BASE = "https://api.github.com"
    
    def __init__(self, token: Optional[str] = None):
        settings = get_settings()
        self._token = token or (settings.github_token.get_secret_value() if settings.github_token else None)
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}" if self._token else "",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    
    async def post_pr_comment(self, payload: PRCommentPayload) -> Optional[int]:
        if not self._token:
            logger.warning("GitHub token not configured, skipping PR comment")
            return None
        
        url = f"{self.API_BASE}/repos/{payload.repository}/issues/{payload.pr_number}/comments"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=self._headers,
                json={"body": payload.body},
            ) as response:
                if response.status == 201:
                    data = await response.json()
                    logger.info(f"Posted PR comment to {payload.repository}#{payload.pr_number}")
                    return data.get("id")
                else:
                    error = await response.text()
                    logger.error(f"Failed to post PR comment: {response.status} - {error}")
                    return None
    
    async def update_pr_comment(self, payload: PRCommentPayload) -> bool:
        if not self._token or not payload.comment_id:
            return False
        
        url = f"{self.API_BASE}/repos/{payload.repository}/issues/comments/{payload.comment_id}"
        
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                url,
                headers=self._headers,
                json={"body": payload.body},
            ) as response:
                if response.status == 200:
                    logger.info(f"Updated PR comment {payload.comment_id}")
                    return True
                return False
    
    async def post_commit_status(
        self,
        repository: str,
        commit_sha: str,
        state: str,
        context: str = "CI/CD Pipeline",
        description: str = "",
        target_url: Optional[str] = None,
    ) -> bool:
        if not self._token:
            return False
        
        url = f"{self.API_BASE}/repos/{repository}/statuses/{commit_sha}"
        
        payload = {
            "state": state,
            "context": context,
            "description": description[:140],
        }
        if target_url:
            payload["target_url"] = target_url
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=self._headers,
                json=payload,
            ) as response:
                if response.status == 201:
                    logger.info(f"Posted commit status: {state} for {commit_sha[:8]}")
                    return True
                return False
    
    def format_build_result_comment(
        self,
        result: BuildResult,
        failure: Optional[FailureRecord] = None,
        recommendations: Optional[List[str]] = None,
    ) -> str:
        if result.status == BuildStatus.SUCCESS:
            emoji = "✅"
            title = "Build Succeeded"
        elif result.status == BuildStatus.FAILED:
            emoji = "❌"
            title = "Build Failed"
        else:
            emoji = "⚠️"
            title = f"Build {result.status.value.title()}"
        
        lines = [f"## {emoji} {title}"]
        lines.append("")
        
        lines.append("| Property | Value |")
        lines.append("|----------|-------|")
        lines.append(f"| **Build ID** | `{result.build_id}` |")
        lines.append(f"| **Status** | {result.status.value} |")
        
        if result.duration_seconds:
            minutes = int(result.duration_seconds // 60)
            seconds = int(result.duration_seconds % 60)
            lines.append(f"| **Duration** | {minutes}m {seconds}s |")
        
        config = result.configuration
        if config.rocm_version:
            lines.append(f"| **ROCm Version** | {config.rocm_version.value} |")
        if config.gpu_architecture:
            lines.append(f"| **GPU Architecture** | {config.gpu_architecture.value} |")
        
        if failure and result.status == BuildStatus.FAILED:
            lines.append("")
            lines.append("### Failure Details")
            lines.append("")
            lines.append(f"**Category:** {failure.category.value}")
            if failure.error_message:
                lines.append("")
                lines.append("```")
                lines.append(str(failure.error_message)[:500])
                lines.append("```")
        
        if recommendations:
            lines.append("")
            lines.append("### Recommendations")
            lines.append("")
            for rec in recommendations[:3]:
                lines.append(f"- {rec}")
        
        if result.logs_url:
            lines.append("")
            lines.append(f"📋 [View Full Logs]({result.logs_url})")
        
        return "\n".join(lines)
    
    def build_status_to_github_state(self, status: BuildStatus) -> str:
        mapping = {
            BuildStatus.PENDING: "pending",
            BuildStatus.RUNNING: "pending",
            BuildStatus.SUCCESS: "success",
            BuildStatus.FAILED: "failure",
            BuildStatus.CANCELLED: "error",
            BuildStatus.TIMEOUT: "failure",
        }
        return mapping.get(status, "error")
