from typing import Optional, Dict, List, Set
from dataclasses import dataclass
import re
from collections import Counter

from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


@dataclass
class SimilarityResult:
    score: float
    method: str
    details: Dict[str, float]


class SimilarityScorer:
    def __init__(self):
        self._weights = {
            "token_jaccard": 0.3,
            "ngram_similarity": 0.3,
            "keyword_match": 0.2,
            "structure_similarity": 0.2,
        }
        self._error_keywords = {
            "error", "failed", "failure", "exception", "undefined",
            "invalid", "cannot", "missing", "timeout", "crash",
            "segfault", "oom", "memory", "gpu", "hip", "rocm",
        }
    
    def score(self, text1: str, text2: str) -> float:
        if not text1 or not text2:
            return 0.0
        
        text1_normalized = self._normalize(text1)
        text2_normalized = self._normalize(text2)
        
        token_score = self._token_jaccard(text1_normalized, text2_normalized)
        ngram_score = self._ngram_similarity(text1_normalized, text2_normalized)
        keyword_score = self._keyword_match_score(text1_normalized, text2_normalized)
        structure_score = self._structure_similarity(text1, text2)
        
        total = (
            token_score * self._weights["token_jaccard"] +
            ngram_score * self._weights["ngram_similarity"] +
            keyword_score * self._weights["keyword_match"] +
            structure_score * self._weights["structure_similarity"]
        )
        
        return min(total, 1.0)
    
    def score_detailed(self, text1: str, text2: str) -> SimilarityResult:
        text1_normalized = self._normalize(text1)
        text2_normalized = self._normalize(text2)
        
        details = {
            "token_jaccard": self._token_jaccard(text1_normalized, text2_normalized),
            "ngram_similarity": self._ngram_similarity(text1_normalized, text2_normalized),
            "keyword_match": self._keyword_match_score(text1_normalized, text2_normalized),
            "structure_similarity": self._structure_similarity(text1, text2),
        }
        
        total = sum(details[k] * self._weights[k] for k in details)
        
        return SimilarityResult(score=min(total, 1.0), method="weighted_composite", details=details)
    
    def _normalize(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r"0x[a-f0-9]+", "<hex>", text)
        text = re.sub(r"\b\d+\b", "<num>", text)
        text = re.sub(r"/[\w/.-]+\.(cpp|c|h|py|hip)", "<file>", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    
    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"\w+|[<>]", text)
    
    def _token_jaccard(self, text1: str, text2: str) -> float:
        tokens1 = set(self._tokenize(text1))
        tokens2 = set(self._tokenize(text2))
        
        if not tokens1 or not tokens2:
            return 0.0
        
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        
        return intersection / union if union else 0.0
    
    def _ngram_similarity(self, text1: str, text2: str, n: int = 3) -> float:
        ngrams1 = self._get_ngrams(text1, n)
        ngrams2 = self._get_ngrams(text2, n)
        
        if not ngrams1 or not ngrams2:
            return 0.0
        
        intersection = len(ngrams1 & ngrams2)
        union = len(ngrams1 | ngrams2)
        
        return intersection / union if union else 0.0
    
    def _get_ngrams(self, text: str, n: int) -> Set[str]:
        return {text[i:i+n] for i in range(len(text) - n + 1)}
    
    def _keyword_match_score(self, text1: str, text2: str) -> float:
        keywords1 = {w for w in self._tokenize(text1) if w in self._error_keywords}
        keywords2 = {w for w in self._tokenize(text2) if w in self._error_keywords}
        
        if not keywords1 or not keywords2:
            return 0.0
        
        intersection = len(keywords1 & keywords2)
        union = len(keywords1 | keywords2)
        
        return intersection / union if union else 0.0
    
    def _structure_similarity(self, text1: str, text2: str) -> float:
        lines1 = text1.strip().split("\n")
        lines2 = text2.strip().split("\n")
        
        if not lines1 or not lines2:
            return 0.0
        
        line_count_ratio = min(len(lines1), len(lines2)) / max(len(lines1), len(lines2))
        
        error_lines1 = sum(1 for l in lines1 if "error" in l.lower())
        error_lines2 = sum(1 for l in lines2 if "error" in l.lower())
        
        if error_lines1 and error_lines2:
            error_ratio = min(error_lines1, error_lines2) / max(error_lines1, error_lines2)
        else:
            error_ratio = 0.0 if (error_lines1 or error_lines2) else 1.0
        
        return (line_count_ratio + error_ratio) / 2
    
    def find_most_similar(
        self,
        query: str,
        candidates: List[str],
        threshold: float = 0.5,
    ) -> List[tuple]:
        results = []
        for i, candidate in enumerate(candidates):
            score = self.score(query, candidate)
            if score >= threshold:
                results.append((i, candidate, score))
        
        results.sort(key=lambda x: x[2], reverse=True)
        return results
