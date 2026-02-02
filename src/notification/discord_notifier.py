from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import aiohttp

from src.common.dto.build import BuildResult
from src.common.config.constants import BuildStatus
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


@dataclass
class DiscordPayload:
    channel: str
    text: str
    blocks: Optional[List[Dict[str, Any]]] = None
    thread_ts: Optional[str] = None
    username: str = "CI/CD Bot"
    icon_emoji: str = ":robot_face:"


class DiscordNotifier:
    def __init__(self, webhook_url: Optional[str] = None, bot_token: Optional[str] = None):
        settings = get_settings()
        self._webhook_url = webhook_url or getattr(settings, "slack_webhook_url", None)
        self._bot_token = bot_token
    
    async def send_message(self, payload: DiscordPayload) -> bool:
        if self._webhook_url:
            return await self._send_via_webhook(payload)
        elif self._bot_token:
            return await self._send_via_api(payload)
        else:
            logger.warning("Slack not configured, skipping notification")
            return False
    
    async def _send_via_webhook(self, payload: DiscordPayload) -> bool:
        data = {
            "text": payload.text,
            "username": payload.username,
            "icon_emoji": payload.icon_emoji,
        }
        
        if payload.blocks:
            data["blocks"] = payload.blocks
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self._webhook_url, json=data) as response:
                if response.status == 200:
                    logger.info(f"Sent Slack message to webhook")
                    return True
                else:
                    error = await response.text()
                    logger.error(f"Slack webhook failed: {response.status} - {error}")
                    return False
    
    async def _send_via_api(self, payload: DiscordPayload) -> bool:
        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {self._bot_token}"}
        
        data = {
            "channel": payload.channel,
            "text": payload.text,
        }
        
        if payload.blocks:
            data["blocks"] = payload.blocks
        if payload.thread_ts:
            data["thread_ts"] = payload.thread_ts
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                result = await response.json()
                if result.get("ok"):
                    logger.info(f"Sent Slack message to {payload.channel}")
                    return True
                else:
                    logger.error(f"Slack API error: {result.get('error')}")
                    return False
    
    def format_build_result_blocks(
        self,
        result: BuildResult,
        include_details: bool = True,
    ) -> List[Dict[str, Any]]:
        if result.status == BuildStatus.SUCCESS:
            color = "good"
            emoji = ":white_check_mark:"
        elif result.status == BuildStatus.FAILED:
            color = "danger"
            emoji = ":x:"
        else:
            color = "warning"
            emoji = ":warning:"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Build {result.status.value.title()}",
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Repository:*\n{result.request.repository}"},
                    {"type": "mrkdwn", "text": f"*Branch:*\n{result.request.branch}"},
                    {"type": "mrkdwn", "text": f"*Commit:*\n`{result.request.commit_sha[:8]}`"},
                    {"type": "mrkdwn", "text": f"*Status:*\n{result.status.value}"},
                ]
            },
        ]
        
        if include_details and result.duration_seconds:
            minutes = int(result.duration_seconds // 60)
            seconds = int(result.duration_seconds % 60)
            blocks.append({
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Duration: {minutes}m {seconds}s | Build ID: `{result.build_id}`"}
                ]
            })
        
        if result.logs_url:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Logs"},
                        "url": result.logs_url,
                    }
                ]
            })
        
        return blocks
