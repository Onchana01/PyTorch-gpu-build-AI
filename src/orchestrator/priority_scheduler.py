from typing import List, Optional, Dict, Set
from datetime import datetime, timezone
from uuid import UUID

from src.common.dto.build import BuildRequest
from src.common.config.constants import Priority
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class PriorityScheduler:
    MAIN_BRANCHES: Set[str] = {"main", "master", "develop", "release"}
    HOTFIX_PREFIXES: List[str] = ["hotfix/", "hotfix-", "fix/"]
    RELEASE_PREFIXES: List[str] = ["release/", "release-", "v"]
    
    def __init__(self):
        self._priority_weights = {
            "is_main_branch": 100,
            "is_release_branch": 80,
            "is_hotfix_branch": 90,
            "has_priority_label": 50,
            "is_ready_for_review": 30,
            "is_draft": -20,
            "is_dependabot": -10,
            "retry_count": -5,
            "queue_age_minutes": 2,
        }
        self._label_priority_boost = {
            "critical": 100,
            "urgent": 80,
            "high-priority": 60,
            "quick-test": 40,
        }
    
    def calculate_priority(self, request: BuildRequest) -> Priority:
        score = self._calculate_priority_score(request)
        
        if score >= 150:
            return Priority.CRITICAL
        elif score >= 80:
            return Priority.HIGH
        elif score >= 20:
            return Priority.NORMAL
        else:
            return Priority.LOW
    
    def _calculate_priority_score(self, request: BuildRequest) -> int:
        score = 50
        
        if self._is_main_branch(request.branch):
            score += self._priority_weights["is_main_branch"]
        
        if self._is_release_branch(request.branch):
            score += self._priority_weights["is_release_branch"]
        
        if self._is_hotfix_branch(request.branch):
            score += self._priority_weights["is_hotfix_branch"]
        
        label_boost = self._get_label_priority_boost(request.metadata.get("labels", []))
        score += label_boost
        
        if request.metadata.get("is_ready_for_review", False):
            score += self._priority_weights["is_ready_for_review"]
        
        if request.metadata.get("is_draft", False):
            score += self._priority_weights["is_draft"]
        
        if self._is_dependabot_pr(request):
            score += self._priority_weights["is_dependabot"]
        
        retry_count = request.metadata.get("retry_count", 0)
        score += retry_count * self._priority_weights["retry_count"]
        
        return score
    
    def _is_main_branch(self, branch: str) -> bool:
        return branch in self.MAIN_BRANCHES
    
    def _is_release_branch(self, branch: str) -> bool:
        return any(branch.startswith(prefix) for prefix in self.RELEASE_PREFIXES)
    
    def _is_hotfix_branch(self, branch: str) -> bool:
        return any(branch.startswith(prefix) for prefix in self.HOTFIX_PREFIXES)
    
    def _get_label_priority_boost(self, labels: List[str]) -> int:
        max_boost = 0
        for label in labels:
            label_lower = label.lower()
            for boost_label, boost_value in self._label_priority_boost.items():
                if boost_label in label_lower:
                    max_boost = max(max_boost, boost_value)
        return max_boost
    
    def _is_dependabot_pr(self, request: BuildRequest) -> bool:
        triggered_by = request.triggered_by.lower() if request.triggered_by else ""
        return "dependabot" in triggered_by or "renovate" in triggered_by
    
    def should_preempt(
        self,
        new_request: BuildRequest,
        running_request: BuildRequest,
    ) -> bool:
        new_priority = self.calculate_priority(new_request)
        running_priority = running_request.priority
        
        if new_priority == Priority.CRITICAL and running_priority != Priority.CRITICAL:
            return True
        
        if new_priority == Priority.CRITICAL and running_priority == Priority.CRITICAL:
            if self._is_hotfix_branch(new_request.branch):
                return True
        
        return False
    
    def get_priority_explanation(self, request: BuildRequest) -> Dict[str, any]:
        factors = []
        score = 50
        
        if self._is_main_branch(request.branch):
            factors.append({
                "factor": "main_branch",
                "description": f"Branch '{request.branch}' is a main branch",
                "score_change": self._priority_weights["is_main_branch"],
            })
            score += self._priority_weights["is_main_branch"]
        
        if self._is_release_branch(request.branch):
            factors.append({
                "factor": "release_branch",
                "description": f"Branch '{request.branch}' is a release branch",
                "score_change": self._priority_weights["is_release_branch"],
            })
            score += self._priority_weights["is_release_branch"]
        
        if self._is_hotfix_branch(request.branch):
            factors.append({
                "factor": "hotfix_branch",
                "description": f"Branch '{request.branch}' is a hotfix branch",
                "score_change": self._priority_weights["is_hotfix_branch"],
            })
            score += self._priority_weights["is_hotfix_branch"]
        
        labels = request.metadata.get("labels", [])
        label_boost = self._get_label_priority_boost(labels)
        if label_boost > 0:
            factors.append({
                "factor": "priority_labels",
                "description": f"Has priority labels: {labels}",
                "score_change": label_boost,
            })
            score += label_boost
        
        priority = self.calculate_priority(request)
        
        return {
            "final_priority": priority.value,
            "total_score": score,
            "base_score": 50,
            "factors": factors,
        }
    
    def compare_requests(
        self,
        request_a: BuildRequest,
        request_b: BuildRequest,
    ) -> int:
        score_a = self._calculate_priority_score(request_a)
        score_b = self._calculate_priority_score(request_b)
        
        if score_a > score_b:
            return -1
        elif score_a < score_b:
            return 1
        
        time_a = request_a.created_at or datetime.now(timezone.utc)
        time_b = request_b.created_at or datetime.now(timezone.utc)
        
        if time_a < time_b:
            return -1
        elif time_a > time_b:
            return 1
        
        return 0
