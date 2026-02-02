from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from src.common.dto.build import BuildResult
from src.common.config.constants import BuildStatus
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


@dataclass
class EmailPayload:
    to: List[str]
    subject: str
    body: str
    html_body: Optional[str] = None
    cc: List[str] = field(default_factory=list)
    reply_to: Optional[str] = None


class EmailNotifier:
    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: int = 587,
        username: Optional[str] = None,
        password: Optional[str] = None,
        from_address: str = "cicd@example.com",
        use_tls: bool = True,
    ):
        settings = get_settings()
        self._smtp_host = smtp_host or getattr(settings, "smtp_host", None)
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_address = from_address
        self._use_tls = use_tls
    
    async def send_email(self, payload: EmailPayload) -> bool:
        if not self._smtp_host:
            logger.warning("SMTP not configured, skipping email notification")
            return False
        
        try:
            def _send():
                import smtplib
                
                msg = MIMEMultipart("alternative")
                msg["Subject"] = payload.subject
                msg["From"] = self._from_address
                msg["To"] = ", ".join(payload.to)
                
                if payload.cc:
                    msg["Cc"] = ", ".join(payload.cc)
                if payload.reply_to:
                    msg["Reply-To"] = payload.reply_to
                
                msg.attach(MIMEText(payload.body, "plain"))
                if payload.html_body:
                    msg.attach(MIMEText(payload.html_body, "html"))
                
                with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                    if self._use_tls:
                        server.starttls()
                    if self._username and self._password:
                        server.login(self._username, self._password)
                    
                    recipients = payload.to + payload.cc
                    server.sendmail(self._from_address, recipients, msg.as_string())
            
            await asyncio.get_event_loop().run_in_executor(None, _send)
            logger.info(f"Sent email to {len(payload.to)} recipients: {payload.subject}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    def format_build_result_email(
        self,
        result: BuildResult,
        failure_details: Optional[str] = None,
    ) -> EmailPayload:
        status_emoji = "✅" if result.status == BuildStatus.SUCCESS else "❌"
        subject = f"{status_emoji} Build {result.status.value.title()}: {result.request.repository}"
        
        lines = [
            f"Build {result.status.value} for {result.request.repository}",
            "",
            f"Build ID: {result.build_id}",
            f"Repository: {result.request.repository}",
            f"Branch: {result.request.branch}",
            f"Commit: {result.request.commit_sha[:8]}",
            f"Status: {result.status.value}",
        ]
        
        if result.duration_seconds:
            lines.append(f"Duration: {int(result.duration_seconds)}s")
        
        if failure_details:
            lines.extend(["", "Error Details:", failure_details])
        
        html = f"""
        <html>
        <body>
        <h2>{status_emoji} Build {result.status.value.title()}</h2>
        <table>
            <tr><td><strong>Repository:</strong></td><td>{result.request.repository}</td></tr>
            <tr><td><strong>Branch:</strong></td><td>{result.request.branch}</td></tr>
            <tr><td><strong>Commit:</strong></td><td>{result.request.commit_sha[:8]}</td></tr>
            <tr><td><strong>Status:</strong></td><td>{result.status.value}</td></tr>
        </table>
        </body>
        </html>
        """
        
        return EmailPayload(
            to=[],
            subject=subject,
            body="\n".join(lines),
            html_body=html,
        )
