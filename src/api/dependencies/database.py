from typing import Generator

from src.storage.database import BuildRepository, FailureRepository
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)

_build_repository: BuildRepository = None
_failure_repository: FailureRepository = None


def get_build_repository() -> BuildRepository:
    global _build_repository
    if _build_repository is None:
        _build_repository = BuildRepository()
    return _build_repository


def get_failure_repository() -> FailureRepository:
    global _failure_repository
    if _failure_repository is None:
        _failure_repository = FailureRepository()
    return _failure_repository


def get_fix_repository():
    from src.analyzer.knowledge_base import KnowledgeBase
    return KnowledgeBase()


def get_metrics_repository():
    from src.monitoring.metrics_collector import MetricsCollector
    return MetricsCollector()


class DatabaseSession:
    def __init__(self):
        self._active = False
    
    def __enter__(self):
        self._active = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._active = False
        if exc_type is not None:
            logger.error(f"Database session error: {exc_val}")
        return False
    
    @property
    def is_active(self) -> bool:
        return self._active


def get_db_session() -> Generator[DatabaseSession, None, None]:
    session = DatabaseSession()
    try:
        with session:
            yield session
    finally:
        pass
