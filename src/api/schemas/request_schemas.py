from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime

from src.common.config.constants import ROCmVersion, GPUArchitecture, Priority


class TriggerBuildRequest(BaseModel):
    repository: str = Field(..., description="Repository in format owner/repo")
    branch: str = Field(default="main", description="Branch to build")
    commit_sha: Optional[str] = Field(None, description="Specific commit SHA")
    rocm_version: Optional[str] = Field(None, description="ROCm version to use")
    gpu_architecture: Optional[str] = Field(None, description="Target GPU architecture")
    priority: Optional[str] = Field(None, description="Build priority")
    environment_variables: Dict[str, str] = Field(default_factory=dict)
    
    @field_validator("repository")
    @classmethod
    def validate_repository(cls, v: str) -> str:
        if "/" not in v:
            raise ValueError("Repository must be in format owner/repo")
        return v


class BuildQueryParams(BaseModel):
    status: Optional[str] = None
    branch: Optional[str] = None
    repository: Optional[str] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class FixFeedbackRequest(BaseModel):
    success: bool = Field(..., description="Whether the fix was successful")
    comment: Optional[str] = Field(None, max_length=1000)
    applied_at: Optional[datetime] = None


class GitHubWebhookPayload(BaseModel):
    action: Optional[str] = None
    ref: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    repository: Optional[Dict[str, Any]] = None
    sender: Optional[Dict[str, Any]] = None
    pull_request: Optional[Dict[str, Any]] = None
    head_commit: Optional[Dict[str, Any]] = None


class AnalyzeLogRequest(BaseModel):
    log_content: str = Field(..., min_length=1, max_length=1000000)
    build_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
