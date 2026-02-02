from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, EmailStr, field_validator

from src.common.dto.base import BaseDTO
from src.common.config.constants import (
    NotificationChannel,
    BuildStatus,
    SeverityLevel,
)


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class BuildStatusEmoji:
    SUCCESS = "✅"
    FAILURE = "❌"
    WARNING = "⚠️"
    RUNNING = "🔄"
    CANCELLED = "🚫"
    PENDING = "⏳"
    
    @classmethod
    def get(cls, status: BuildStatus) -> str:
        mapping = {
            BuildStatus.SUCCESS: cls.SUCCESS,
            BuildStatus.FAILURE: cls.FAILURE,
            BuildStatus.RUNNING: cls.RUNNING,
            BuildStatus.CANCELLED: cls.CANCELLED,
            BuildStatus.PENDING: cls.PENDING,
            BuildStatus.TIMEOUT: cls.WARNING,
            BuildStatus.QUEUED: cls.PENDING,
            BuildStatus.SKIPPED: cls.CANCELLED,
        }
        return mapping.get(status, cls.WARNING)


class FailureSummaryItem(BaseModel):
    category: str
    component: Optional[str] = None
    error_excerpt: str
    confidence_score: float = Field(default=0.0)
    has_recommended_fix: bool = Field(default=False)


class RecommendedAction(BaseModel):
    order: int
    action_type: str
    description: str
    command: Optional[str] = None
    confidence: float = Field(default=0.0)
    effort_estimate: str = Field(default="low")
    documentation_url: Optional[str] = None


class PRComment(BaseModel):
    pr_number: int
    repository: str
    commit_sha: str
    build_status: BuildStatus
    build_id: UUID
    build_duration_seconds: Optional[float] = None
    
    summary_table: List[Dict[str, str]] = Field(default_factory=list)
    failure_summaries: List[FailureSummaryItem] = Field(default_factory=list)
    recommended_actions: List[RecommendedAction] = Field(default_factory=list)
    
    test_summary: Optional[str] = None
    test_pass_rate: Optional[float] = None
    
    log_url: Optional[str] = None
    dashboard_url: Optional[str] = None
    artifact_urls: Dict[str, str] = Field(default_factory=dict)
    
    similar_failure_links: List[str] = Field(default_factory=list)
    documentation_links: List[str] = Field(default_factory=list)
    
    previous_comment_id: Optional[int] = None
    is_update: bool = Field(default=False)

    def generate_markdown(self) -> str:
        lines = []
        
        emoji = BuildStatusEmoji.get(self.build_status)
        lines.append(f"## {emoji} Build {self.build_status.value.title()}")
        lines.append("")
        
        if self.build_duration_seconds:
            duration_min = self.build_duration_seconds / 60
            lines.append(f"**Duration:** {duration_min:.1f} minutes")
        lines.append(f"**Commit:** `{self.commit_sha[:8]}`")
        lines.append("")
        
        if self.summary_table:
            lines.append("### Configuration Matrix")
            lines.append("")
            headers = list(self.summary_table[0].keys())
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in self.summary_table:
                lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
            lines.append("")
        
        if self.failure_summaries:
            lines.append("### Failure Summary")
            lines.append("")
            for failure in self.failure_summaries:
                lines.append(f"#### {failure.category}")
                if failure.component:
                    lines.append(f"**Component:** {failure.component}")
                lines.append("```")
                lines.append(failure.error_excerpt[:500])
                lines.append("```")
                lines.append("")
        
        if self.recommended_actions:
            lines.append("### Recommended Actions")
            lines.append("")
            for action in self.recommended_actions:
                confidence_pct = int(action.confidence * 100)
                lines.append(f"{action.order}. **{action.description}** ({confidence_pct}% confidence)")
                if action.command:
                    lines.append(f"   ```bash")
                    lines.append(f"   {action.command}")
                    lines.append(f"   ```")
            lines.append("")
        
        if self.log_url or self.dashboard_url:
            lines.append("### Resources")
            if self.log_url:
                lines.append(f"- [View Full Logs]({self.log_url})")
            if self.dashboard_url:
                lines.append(f"- [Build Dashboard]({self.dashboard_url})")
            for name, url in self.artifact_urls.items():
                lines.append(f"- [{name}]({url})")
        
        return "\n".join(lines)


class EmailMessage(BaseModel):
    to_addresses: List[EmailStr]
    cc_addresses: List[EmailStr] = Field(default_factory=list)
    bcc_addresses: List[EmailStr] = Field(default_factory=list)
    subject: str
    body_text: str
    body_html: Optional[str] = None
    reply_to: Optional[EmailStr] = None
    priority: NotificationPriority = Field(default=NotificationPriority.NORMAL)
    attachments: List[str] = Field(default_factory=list)
    headers: Dict[str, str] = Field(default_factory=dict)


class SlackMessage(BaseModel):
    channel: str
    text: str
    thread_ts: Optional[str] = None
    blocks: List[Dict[str, Any]] = Field(default_factory=list)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    username: str = Field(default="ROCm CI/CD Bot")
    icon_emoji: str = Field(default=":rocket:")
    unfurl_links: bool = Field(default=False)
    unfurl_media: bool = Field(default=True)

    def add_section(self, text: str) -> None:
        self.blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text}
        })

    def add_divider(self) -> None:
        self.blocks.append({"type": "divider"})

    def add_button(self, text: str, action_id: str, url: Optional[str] = None) -> None:
        button = {
            "type": "button",
            "text": {"type": "plain_text", "text": text},
            "action_id": action_id,
        }
        if url:
            button["url"] = url
        
        if not self.blocks or self.blocks[-1].get("type") != "actions":
            self.blocks.append({"type": "actions", "elements": []})
        
        self.blocks[-1]["elements"].append(button)


class TeamsMessage(BaseModel):
    webhook_url: str
    title: str
    text: str
    theme_color: str = Field(default="0076D7")
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    potential_actions: List[Dict[str, Any]] = Field(default_factory=list)


class WebhookPayload(BaseModel):
    event_type: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    payload: Dict[str, Any] = Field(default_factory=dict)
    signature: Optional[str] = None
    retry_count: int = Field(default=0)


class NotificationRequest(BaseDTO):
    channels: List[NotificationChannel]
    priority: NotificationPriority = Field(default=NotificationPriority.NORMAL)
    build_id: Optional[UUID] = None
    pr_number: Optional[int] = None
    repository: Optional[str] = None
    recipients: List[str] = Field(default_factory=list)
    
    pr_comment: Optional[PRComment] = None
    email_message: Optional[EmailMessage] = None
    slack_message: Optional[SlackMessage] = None
    teams_message: Optional[TeamsMessage] = None
    webhook_payload: Optional[WebhookPayload] = None
    
    scheduled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    deduplicate_key: Optional[str] = None


class NotificationResult(BaseModel):
    request_id: UUID
    channel: NotificationChannel
    success: bool
    sent_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    response_id: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = Field(default=0)
    delivery_status: str = Field(default="unknown")


class NotificationPreferences(BaseModel):
    user_id: str
    enabled_channels: List[NotificationChannel] = Field(
        default_factory=lambda: [NotificationChannel.GITHUB_PR]
    )
    email_address: Optional[EmailStr] = None
    slack_user_id: Optional[str] = None
    notify_on_success: bool = Field(default=False)
    notify_on_failure: bool = Field(default=True)
    notify_on_flaky: bool = Field(default=True)
    digest_frequency: str = Field(default="immediate")
    quiet_hours_start: Optional[int] = None
    quiet_hours_end: Optional[int] = None
    mention_in_threads: bool = Field(default=True)
