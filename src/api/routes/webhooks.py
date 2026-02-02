from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, Header, status
import hmac
import hashlib
import json

from src.orchestrator.webhook_receiver import WebhookReceiver
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks")

_webhook_receiver = WebhookReceiver()


@router.post("/github", status_code=status.HTTP_200_OK)
async def github_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
) -> Dict[str, str]:
    body = await request.body()
    
    if x_hub_signature_256:
        settings = get_settings()
        if settings.github_webhook_secret:
            expected_signature = _compute_signature(body, settings.github_webhook_secret.get_secret_value())
            if not hmac.compare_digest(expected_signature, x_hub_signature_256):
                logger.warning(f"Invalid webhook signature for delivery {x_github_delivery}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature",
                )
    
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )
    
    event_type = x_github_event or "unknown"
    logger.info(f"Received GitHub webhook: {event_type} (delivery: {x_github_delivery})")
    
    if event_type == "push":
        build_request = await _webhook_receiver.handle_push_event(payload)
        if build_request:
            return {"status": "accepted", "build_id": str(build_request.id)}
    
    elif event_type == "pull_request":
        action = payload.get("action")
        if action in ["opened", "synchronize", "reopened"]:
            build_request = await _webhook_receiver.handle_pull_request_event(payload)
            if build_request:
                return {"status": "accepted", "build_id": str(build_request.id)}
    
    elif event_type == "workflow_dispatch":
        build_request = await _webhook_receiver.handle_workflow_dispatch(payload)
        if build_request:
            return {"status": "accepted", "build_id": str(build_request.id)}
    
    return {"status": "ignored", "event": event_type}


@router.post("/gitlab", status_code=status.HTTP_200_OK)
async def gitlab_webhook(
    request: Request,
    x_gitlab_token: Optional[str] = Header(None, alias="X-Gitlab-Token"),
) -> Dict[str, str]:
    logger.info("Received GitLab webhook (not fully implemented)")
    return {"status": "received", "message": "GitLab integration pending"}


def _compute_signature(payload: bytes, secret: str) -> str:
    signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={signature}"
