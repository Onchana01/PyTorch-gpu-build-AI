from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path

from src.analyzer.pattern_matcher import FailurePattern
from src.analyzer.recommendation_engine import FixRecommendation, RecommendationType
from src.common.config.constants import FailureCategory
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


@dataclass
class KnowledgeEntry:
    entry_id: str
    signature: str
    category: FailureCategory
    pattern_id: Optional[str] = None
    description: str = ""
    recommendations: List[FixRecommendation] = field(default_factory=list)
    occurrence_count: int = 1
    last_seen: Optional[datetime] = None
    success_rate: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class KnowledgeBase:
    def __init__(self, storage_path: Optional[str] = None):
        self._storage_path = Path(storage_path) if storage_path else None
        self._entries: Dict[str, KnowledgeEntry] = {}
        self._signature_index: Dict[str, str] = {}
        
        if self._storage_path and self._storage_path.exists():
            self._load()
    
    def add_entry(self, entry: KnowledgeEntry) -> None:
        self._entries[entry.entry_id] = entry
        self._signature_index[entry.signature] = entry.entry_id
        logger.debug(f"Added knowledge entry: {entry.entry_id}")
    
    def get_entry(self, entry_id: str) -> Optional[KnowledgeEntry]:
        return self._entries.get(entry_id)
    
    def get_by_signature(self, signature: str) -> Optional[KnowledgeEntry]:
        entry_id = self._signature_index.get(signature)
        if entry_id:
            return self._entries.get(entry_id)
        return None
    
    def get_recommendations(self, signature: str) -> List[FixRecommendation]:
        entry = self.get_by_signature(signature)
        if entry:
            return entry.recommendations
        return []
    
    def record_occurrence(
        self,
        signature: str,
        category: FailureCategory,
        pattern_id: Optional[str] = None,
    ) -> KnowledgeEntry:
        entry = self.get_by_signature(signature)
        
        if entry:
            entry.occurrence_count += 1
            entry.last_seen = datetime.now(timezone.utc)
        else:
            from uuid import uuid4
            entry = KnowledgeEntry(
                entry_id=str(uuid4()),
                signature=signature,
                category=category,
                pattern_id=pattern_id,
                occurrence_count=1,
                last_seen=datetime.now(timezone.utc),
            )
            self.add_entry(entry)
        
        return entry
    
    def record_fix_result(
        self,
        signature: str,
        recommendation_id: str,
        success: bool,
    ) -> None:
        entry = self.get_by_signature(signature)
        if not entry:
            return
        
        total = entry.metadata.get("total_fixes", 0) + 1
        successes = entry.metadata.get("successful_fixes", 0) + (1 if success else 0)
        
        entry.metadata["total_fixes"] = total
        entry.metadata["successful_fixes"] = successes
        entry.success_rate = successes / total
        
        logger.info(f"Updated success rate for {signature}: {entry.success_rate:.2%}")
    
    def search(
        self,
        category: Optional[FailureCategory] = None,
        min_occurrences: int = 1,
        limit: int = 100,
    ) -> List[KnowledgeEntry]:
        results = []
        
        for entry in self._entries.values():
            if category and entry.category != category:
                continue
            if entry.occurrence_count < min_occurrences:
                continue
            results.append(entry)
        
        results.sort(key=lambda e: e.occurrence_count, reverse=True)
        return results[:limit]
    
    def get_statistics(self) -> Dict[str, Any]:
        category_counts: Dict[str, int] = {}
        total_occurrences = 0
        
        for entry in self._entries.values():
            cat = entry.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
            total_occurrences += entry.occurrence_count
        
        return {
            "total_entries": len(self._entries),
            "total_occurrences": total_occurrences,
            "category_distribution": category_counts,
            "average_success_rate": sum(e.success_rate for e in self._entries.values()) / max(len(self._entries), 1),
        }
    
    def save(self) -> None:
        if not self._storage_path:
            return
        
        data = {
            "entries": [self._serialize_entry(e) for e in self._entries.values()],
            "version": "1.0",
        }
        
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._storage_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info(f"Saved {len(self._entries)} knowledge entries")
    
    def _load(self) -> None:
        try:
            with open(self._storage_path, "r") as f:
                data = json.load(f)
            
            for entry_data in data.get("entries", []):
                entry = self._deserialize_entry(entry_data)
                self.add_entry(entry)
            
            logger.info(f"Loaded {len(self._entries)} knowledge entries")
        except Exception as e:
            logger.error(f"Failed to load knowledge base: {e}")
    
    def _serialize_entry(self, entry: KnowledgeEntry) -> Dict[str, Any]:
        return {
            "entry_id": entry.entry_id,
            "signature": entry.signature,
            "category": entry.category.value,
            "pattern_id": entry.pattern_id,
            "description": entry.description,
            "occurrence_count": entry.occurrence_count,
            "last_seen": entry.last_seen.isoformat() if entry.last_seen else None,
            "success_rate": entry.success_rate,
            "metadata": entry.metadata,
        }
    
    def _deserialize_entry(self, data: Dict[str, Any]) -> KnowledgeEntry:
        return KnowledgeEntry(
            entry_id=data["entry_id"],
            signature=data["signature"],
            category=FailureCategory(data["category"]),
            pattern_id=data.get("pattern_id"),
            description=data.get("description", ""),
            occurrence_count=data.get("occurrence_count", 1),
            last_seen=datetime.fromisoformat(data["last_seen"]) if data.get("last_seen") else None,
            success_rate=data.get("success_rate", 0.0),
            metadata=data.get("metadata", {}),
        )
