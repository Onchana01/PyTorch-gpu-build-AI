from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import asyncio

from src.notification.github_notifier import GitHubNotifier, PRCommentPayload
from src.notification.email_notifier import EmailNotifier, EmailPayload
from src.notification.discord_notifier import DiscordNotifier, DiscordPayload
from src.common.dto.build import BuildResult
from src.common.dto.failure import FailureRecord
from src.common.config.constants import BuildStatus
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class NotificationChannel(str, Enum):
    GITHUB = "github"
    EMAIL = "email"
    DISCORD = "discord"


@dataclass
class NotificationConfig:
    enabled_channels: List[NotificationChannel]
    notify_on_success: bool = False
    notify_on_failure: bool = True
    notify_on_recovery: bool = True
    github_enabled: bool = True
    email_recipients: List[str] = None
    discord_channel: str = "#builds"
    
    def __post_init__(self):
        if self.email_recipients is None:
            self.email_recipients = []


class NotificationManager:
    def __init__(self, config: Optional[NotificationConfig] = None):
        self._config = config or NotificationConfig(
            enabled_channels=[NotificationChannel.GITHUB],
        )
        
        self._github = GitHubNotifier()
        self._email = EmailNotifier()
        self._discord = DiscordNotifier()
        
        self._previous_status: Dict[str, BuildStatus] = {}
    
    async def notify_build_result(
        self,
        result: BuildResult,
        failure: Optional[FailureRecord] = None,
        recommendations: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        results = {}
        
        should_notify = self._should_notify(result)
        if not should_notify:
            logger.debug(f"Skipping notification for build {result.build_id}")
            return results
        
        tasks = []
        
        if NotificationChannel.GITHUB in self._config.enabled_channels:
            tasks.append(self._notify_github(result, failure, recommendations))
        
        if NotificationChannel.EMAIL in self._config.enabled_channels:
            tasks.append(self._notify_email(result, failure))
        
        if NotificationChannel.DISCORD in self._config.enabled_channels:
            tasks.append(self._notify_discord(result))
        
        if tasks:
            channel_results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, channel in enumerate(self._config.enabled_channels):
                if i < len(channel_results):
                    result_val = channel_results[i]
                    results[channel.value] = result_val if isinstance(result_val, bool) else False
        
        self._previous_status[str(result.build_id)] = result.status
        
        return results
    
    def _should_notify(self, result: BuildResult) -> bool:
        if result.status == BuildStatus.SUCCESS:
            if self._config.notify_on_success:
                return True
            
            prev = self._previous_status.get(str(result.request.id))
            if prev == BuildStatus.FAILED and self._config.notify_on_recovery:
                return True
            
            return False
        
        if result.status == BuildStatus.FAILED:
            return self._config.notify_on_failure
        
        return False
    
    async def _notify_github(
        self,
        result: BuildResult,
        failure: Optional[FailureRecord],
        recommendations: Optional[List[str]],
    ) -> bool:
        if not result.request.pr_number:
            state = self._github.build_status_to_github_state(result.status)
            return await self._github.post_commit_status(
                repository=result.request.repository,
                commit_sha=result.request.commit_sha,
                state=state,
                description=f"Build {result.status.value}",
            )
        
        body = self._github.format_build_result_comment(result, failure, recommendations)
        
        payload = PRCommentPayload(
            repository=result.request.repository,
            pr_number=result.request.pr_number,
            body=body,
        )
        
        comment_id = await self._github.post_pr_comment(payload)
        return comment_id is not None
    
    async def _notify_email(
        self,
        result: BuildResult,
        failure: Optional[FailureRecord],
    ) -> bool:
        if not self._config.email_recipients:
            return False
        
        failure_details = str(failure.error_message) if failure else None
        payload = self._email.format_build_result_email(result, failure_details)
        payload.to = self._config.email_recipients
        
        return await self._email.send_email(payload)
    
    async def _notify_discord(self, result: BuildResult) -> bool:
        blocks = self._discord.format_build_result_blocks(result)
        
        payload = DiscordPayload(
            channel=self._config.discord_channel,
            text=f"Build {result.status.value} for {result.request.repository}",
            blocks=blocks,
        )
        
        return await self._discord.send_message(payload)
    
    async def send_custom_notification(
        self,
        channels: List[NotificationChannel],
        message: str,
        title: Optional[str] = None,
    ) -> Dict[str, bool]:
        results = {}
        
        if NotificationChannel.DISCORD in channels:
            payload = DiscordPayload(
                channel=self._config.discord_channel,
                text=message,
            )
            results["discord"] = await self._discord.send_message(payload)
        
        if NotificationChannel.EMAIL in channels and self._config.email_recipients:
            payload = EmailPayload(
                to=self._config.email_recipients,
                subject=title or "CI/CD Notification",
                body=message,
            )
            results["email"] = await self._email.send_email(payload)
        
        return results
