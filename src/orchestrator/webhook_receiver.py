from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from uuid import uuid4
import hmac
import hashlib
import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, Header, BackgroundTasks
from pydantic import BaseModel

from src.common.dto.build import BuildRequest, BuildConfiguration
from src.common.config.constants import Priority, ROCmVersion, GPUArchitecture
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger
from src.common.security.authentication import verify_webhook_signature


logger = get_logger(__name__)


class WebhookPayload(BaseModel):
    action: Optional[str] = None
    ref: Optional[str] = None
    ref_type: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    repository: Optional[Dict[str, Any]] = None
    sender: Optional[Dict[str, Any]] = None
    pusher: Optional[Dict[str, Any]] = None
    commits: Optional[List[Dict[str, Any]]] = None
    head_commit: Optional[Dict[str, Any]] = None
    pull_request: Optional[Dict[str, Any]] = None
    number: Optional[int] = None


class WebhookReceiver:
    def __init__(self, coordinator=None):
        self._coordinator = coordinator
        self._settings = get_settings()
        self.app = self._create_app()
    
    def _create_app(self) -> FastAPI:
        app = FastAPI(
            title="ROCm CI/CD Webhook Receiver",
            description="Receives GitHub webhooks for CI/CD pipeline",
            version="1.0.0",
        )
        
        @app.get("/health")
        async def health_check():
            return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}
        
        @app.post("/webhook/github")
        async def github_webhook(
            request: Request,
            background_tasks: BackgroundTasks,
            x_github_event: str = Header(None, alias="X-GitHub-Event"),
            x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
            x_github_delivery: str = Header(None, alias="X-GitHub-Delivery"),
        ):
            body = await request.body()
            
            if self._settings.github_webhook_secret:
                if not self._verify_signature(body, x_hub_signature_256):
                    logger.warning(f"Invalid webhook signature for delivery {x_github_delivery}")
                    raise HTTPException(status_code=401, detail="Invalid signature")
            
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON payload")
            
            logger.info(f"Received GitHub webhook: event={x_github_event}, delivery={x_github_delivery}")
            
            build_request = self._parse_webhook_event(x_github_event, payload)
            
            if build_request:
                if self._coordinator:
                    background_tasks.add_task(self._coordinator.submit_build, build_request)
                    return {
                        "status": "accepted",
                        "build_id": str(build_request.id),
                        "message": "Build request queued",
                    }
                else:
                    return {
                        "status": "accepted",
                        "build_id": str(build_request.id),
                        "message": "Build request created (coordinator not configured)",
                    }
            
            return {"status": "ignored", "message": f"Event {x_github_event} does not trigger build"}
        
        @app.post("/webhook/test")
        async def test_webhook(request: Request):
            body = await request.body()
            return {
                "status": "received",
                "content_length": len(body),
            }
        
        return app
    
    def _verify_signature(self, payload: bytes, signature: str) -> bool:
        if not signature:
            return False
        
        secret = self._settings.github_webhook_secret.get_secret_value()
        expected_signature = "sha256=" + hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
    
    def _parse_webhook_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> Optional[BuildRequest]:
        if event_type == "push":
            return self._handle_push_event(payload)
        elif event_type == "pull_request":
            return self._handle_pull_request_event(payload)
        elif event_type == "workflow_dispatch":
            return self._handle_workflow_dispatch(payload)
        elif event_type == "issue_comment":
            return self._handle_issue_comment(payload)
        else:
            logger.debug(f"Ignoring webhook event type: {event_type}")
            return None
    
    def _handle_push_event(self, payload: Dict[str, Any]) -> Optional[BuildRequest]:
        ref = payload.get("ref", "")
        
        if not ref.startswith("refs/heads/"):
            logger.debug(f"Ignoring non-branch push: {ref}")
            return None
        
        branch = ref.replace("refs/heads/", "")
        
        if payload.get("deleted", False):
            logger.debug(f"Ignoring branch deletion: {branch}")
            return None
        
        if self._should_skip_push(payload):
            logger.debug(f"Skipping push based on commit message")
            return None
        
        repository = payload.get("repository", {})
        head_commit = payload.get("head_commit", {}) or {}
        
        return BuildRequest(
            repository=repository.get("full_name", ""),
            commit_sha=payload.get("after", ""),
            branch=branch,
            triggered_by=payload.get("pusher", {}).get("name", "unknown"),
            configurations=self._get_default_configurations(),
            metadata={
                "event_type": "push",
                "commit_message": head_commit.get("message", ""),
                "commit_author": head_commit.get("author", {}).get("name", ""),
                "repository_url": repository.get("html_url", ""),
            }
        )
    
    def _handle_pull_request_event(self, payload: Dict[str, Any]) -> Optional[BuildRequest]:
        action = payload.get("action", "")
        
        pr_trigger_actions = ["opened", "synchronize", "reopened", "ready_for_review"]
        if action not in pr_trigger_actions:
            logger.debug(f"Ignoring PR action: {action}")
            return None
        
        pr = payload.get("pull_request", {})
        repository = payload.get("repository", {})
        
        labels = [label.get("name", "") for label in pr.get("labels", [])]
        
        if self._should_skip_pr(pr, labels):
            logger.debug(f"Skipping PR build based on labels or state")
            return None
        
        return BuildRequest(
            repository=repository.get("full_name", ""),
            commit_sha=pr.get("head", {}).get("sha", ""),
            branch=pr.get("head", {}).get("ref", ""),
            pr_number=payload.get("number"),
            triggered_by=pr.get("user", {}).get("login", "unknown"),
            configurations=self._get_configurations_for_pr(pr, labels),
            metadata={
                "event_type": "pull_request",
                "action": action,
                "pr_title": pr.get("title", ""),
                "pr_url": pr.get("html_url", ""),
                "is_draft": pr.get("draft", False),
                "is_ready_for_review": action == "ready_for_review" or not pr.get("draft", False),
                "labels": labels,
                "base_branch": pr.get("base", {}).get("ref", ""),
            }
        )
    
    def _handle_workflow_dispatch(self, payload: Dict[str, Any]) -> Optional[BuildRequest]:
        repository = payload.get("repository", {})
        inputs = payload.get("inputs", {})
        
        rocm_version_str = inputs.get("rocm_version", "6.0")
        gpu_arch_str = inputs.get("gpu_architecture", "gfx90a")
        
        try:
            rocm_version = ROCmVersion(rocm_version_str)
        except ValueError:
            rocm_version = ROCmVersion.ROCM_6_0
        
        try:
            gpu_arch = GPUArchitecture(gpu_arch_str)
        except ValueError:
            gpu_arch = GPUArchitecture.GFX90A
        
        config = BuildConfiguration(
            rocm_version=rocm_version,
            gpu_architecture=gpu_arch,
            build_type=inputs.get("build_type", "release"),
            python_version=inputs.get("python_version", "3.10"),
        )
        
        return BuildRequest(
            repository=repository.get("full_name", ""),
            commit_sha=payload.get("ref", "").replace("refs/heads/", ""),
            branch=payload.get("ref", "").replace("refs/heads/", ""),
            triggered_by=payload.get("sender", {}).get("login", "workflow_dispatch"),
            configurations=[config],
            priority=Priority.HIGH,
            metadata={
                "event_type": "workflow_dispatch",
                "inputs": inputs,
            }
        )
    
    def _handle_issue_comment(self, payload: Dict[str, Any]) -> Optional[BuildRequest]:
        action = payload.get("action", "")
        if action != "created":
            return None
        
        comment_body = payload.get("comment", {}).get("body", "")
        
        if not any(cmd in comment_body.lower() for cmd in ["/rebuild", "/retry", "/test"]):
            return None
        
        issue = payload.get("issue", {})
        if not issue.get("pull_request"):
            return None
        
        repository = payload.get("repository", {})
        
        logger.info(f"Build triggered by comment command: {comment_body}")
        
        return BuildRequest(
            repository=repository.get("full_name", ""),
            commit_sha="",
            branch="",
            pr_number=issue.get("number"),
            triggered_by=payload.get("sender", {}).get("login", "unknown"),
            configurations=self._get_default_configurations(),
            metadata={
                "event_type": "issue_comment",
                "command": comment_body,
                "comment_url": payload.get("comment", {}).get("html_url", ""),
            }
        )
    
    def _should_skip_push(self, payload: Dict[str, Any]) -> bool:
        head_commit = payload.get("head_commit", {}) or {}
        message = head_commit.get("message", "").lower()
        
        skip_patterns = ["[skip ci]", "[ci skip]", "[no ci]", "[skip build]"]
        return any(pattern in message for pattern in skip_patterns)
    
    def _should_skip_pr(self, pr: Dict[str, Any], labels: List[str]) -> bool:
        skip_labels = ["skip-ci", "documentation", "wip"]
        if any(label.lower() in skip_labels for label in labels):
            return True
        
        return False
    
    def _get_default_configurations(self) -> List[BuildConfiguration]:
        return [
            BuildConfiguration(
                rocm_version=ROCmVersion.ROCM_6_0,
                gpu_architecture=GPUArchitecture.GFX90A,
                build_type="release",
                python_version="3.10",
            )
        ]
    
    def _get_configurations_for_pr(
        self,
        pr: Dict[str, Any],
        labels: List[str],
    ) -> List[BuildConfiguration]:
        if "quick-test" in [l.lower() for l in labels]:
            return [
                BuildConfiguration(
                    rocm_version=ROCmVersion.ROCM_6_0,
                    gpu_architecture=GPUArchitecture.GFX90A,
                    build_type="release",
                    python_version="3.10",
                )
            ]
        
        if "full-matrix" in [l.lower() for l in labels]:
            return self._get_full_matrix_configurations()
        
        return self._get_default_configurations()
    
    def _get_full_matrix_configurations(self) -> List[BuildConfiguration]:
        configurations = []
        
        for rocm_version in [ROCmVersion.ROCM_5_7, ROCmVersion.ROCM_6_0]:
            for gpu_arch in [GPUArchitecture.GFX90A, GPUArchitecture.GFX908]:
                configurations.append(
                    BuildConfiguration(
                        rocm_version=rocm_version,
                        gpu_architecture=gpu_arch,
                        build_type="release",
                        python_version="3.10",
                    )
                )
        
        return configurations
    
    def set_coordinator(self, coordinator) -> None:
        self._coordinator = coordinator
        logger.info("Coordinator attached to webhook receiver")


def create_webhook_app(coordinator=None) -> FastAPI:
    receiver = WebhookReceiver(coordinator=coordinator)
    return receiver.app
