from typing import Optional, Dict, Any, List, TypeVar, Generic
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from uuid import UUID
from datetime import datetime, timezone
import asyncio

from src.common.dto.build import BuildRequest, BuildResult
from src.common.dto.failure import FailureRecord
from src.common.config.constants import BuildStatus, FailureCategory
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger
from src.common.exceptions.storage_exceptions import DatabaseError, RecordNotFoundError


logger = get_logger(__name__)

T = TypeVar("T")


class DatabaseRepository(ABC, Generic[T]):
    @abstractmethod
    async def create(self, entity: T) -> T:
        raise NotImplementedError("Subclasses must implement create method")
    
    @abstractmethod
    async def get(self, entity_id: str) -> Optional[T]:
        raise NotImplementedError("Subclasses must implement get method")
    
    @abstractmethod
    async def update(self, entity_id: str, updates: Dict[str, Any]) -> Optional[T]:
        raise NotImplementedError("Subclasses must implement update method")
    
    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        raise NotImplementedError("Subclasses must implement delete method")
    
    @abstractmethod
    async def list(self, filters: Optional[Dict[str, Any]] = None, limit: int = 100, offset: int = 0) -> List[T]:
        raise NotImplementedError("Subclasses must implement list method")


@dataclass
class MongoDBConfig:
    connection_url: str
    database_name: str
    max_pool_size: int = 10
    min_pool_size: int = 1
    server_selection_timeout_ms: int = 5000
    connect_timeout_ms: int = 10000


class MongoDBConnection:
    def __init__(self, config: Optional[MongoDBConfig] = None):
        if config is None:
            settings = get_settings()
            config = MongoDBConfig(
                connection_url=settings.mongodb_url,
                database_name=settings.mongodb_database,
                max_pool_size=settings.mongodb_max_pool_size,
                min_pool_size=settings.mongodb_min_pool_size,
            )
        self._config = config
        self._client = None
        self._db = None
        self._initialized = False
    
    async def initialize(self) -> None:
        if self._initialized:
            return
        
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            
            self._client = AsyncIOMotorClient(
                self._config.connection_url,
                maxPoolSize=self._config.max_pool_size,
                minPoolSize=self._config.min_pool_size,
                serverSelectionTimeoutMS=self._config.server_selection_timeout_ms,
                connectTimeoutMS=self._config.connect_timeout_ms,
            )
            
            self._db = self._client[self._config.database_name]
            
            await self._client.admin.command("ping")
            
            self._initialized = True
            logger.info(f"MongoDB connection initialized: {self._config.database_name}")
            
        except ImportError as e:
            logger.error(f"motor package not installed: {e}")
            raise DatabaseError(
                message="MongoDB driver (motor) not installed. Install with: pip install motor",
                database_type="mongodb"
            )
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise DatabaseError(
                message=f"MongoDB connection failed: {str(e)}",
                database_type="mongodb"
            )
    
    async def close(self) -> None:
        if self._client:
            self._client.close()
            self._initialized = False
            logger.info("MongoDB connection closed")
    
    def get_collection(self, name: str):
        if not self._initialized:
            raise DatabaseError(
                message="MongoDB not initialized. Call initialize() first.",
                database_type="mongodb"
            )
        return self._db[name]
    
    @property
    def is_connected(self) -> bool:
        return self._initialized and self._client is not None
    
    async def health_check(self) -> Dict[str, Any]:
        try:
            if not self._client:
                return {"status": "disconnected", "error": "Client not initialized"}
            
            result = await self._client.admin.command("ping")
            return {"status": "healthy", "ping": result}
        except Exception as e:
            logger.error(f"MongoDB health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}


_db_connection: Optional[MongoDBConnection] = None


async def get_db_connection() -> MongoDBConnection:
    global _db_connection
    if _db_connection is None:
        _db_connection = MongoDBConnection()
        await _db_connection.initialize()
    return _db_connection


class InMemoryRepository(DatabaseRepository[T]):
    def __init__(self):
        self._storage: Dict[str, T] = {}
        logger.info(f"InMemoryRepository initialized for {self.__class__.__name__}")
    
    async def create(self, entity: T) -> T:
        entity_id = self._get_entity_id(entity)
        if not entity_id:
            raise DatabaseError(
                message="Entity must have an id or build_id attribute",
                database_type="memory"
            )
        self._storage[entity_id] = entity
        logger.debug(f"Created entity: {entity_id}")
        return entity
    
    async def get(self, entity_id: str) -> Optional[T]:
        entity = self._storage.get(entity_id)
        if entity is None:
            logger.debug(f"Entity not found: {entity_id}")
        return entity
    
    async def update(self, entity_id: str, updates: Dict[str, Any]) -> Optional[T]:
        entity = self._storage.get(entity_id)
        if entity is None:
            logger.warning(f"Cannot update, entity not found: {entity_id}")
            return None
        
        for key, value in updates.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
            else:
                logger.warning(f"Entity {entity_id} has no attribute {key}")
        
        logger.debug(f"Updated entity: {entity_id}")
        return entity
    
    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._storage:
            del self._storage[entity_id]
            logger.debug(f"Deleted entity: {entity_id}")
            return True
        logger.warning(f"Cannot delete, entity not found: {entity_id}")
        return False
    
    async def list(self, filters: Optional[Dict[str, Any]] = None, limit: int = 100, offset: int = 0) -> List[T]:
        items = list(self._storage.values())
        
        if filters:
            for key, value in filters.items():
                items = [i for i in items if getattr(i, key, None) == value]
        
        return items[offset:offset + limit]
    
    def _get_entity_id(self, entity: T) -> Optional[str]:
        for attr in ["id", "build_id", "failure_id", "entity_id"]:
            if hasattr(entity, attr):
                return str(getattr(entity, attr))
        return None


class MongoRepository(DatabaseRepository[T]):
    def __init__(self, collection_name: str):
        self._collection_name = collection_name
        self._connection: Optional[MongoDBConnection] = None
    
    async def _get_collection(self):
        if self._connection is None:
            self._connection = await get_db_connection()
        return self._connection.get_collection(self._collection_name)
    
    async def create(self, entity: T) -> T:
        try:
            collection = await self._get_collection()
            doc = self._entity_to_document(entity)
            result = await collection.insert_one(doc)
            logger.debug(f"Created document in {self._collection_name}: {result.inserted_id}")
            return entity
        except Exception as e:
            logger.error(f"Failed to create document in {self._collection_name}: {e}")
            raise DatabaseError(
                message=f"Failed to create document: {str(e)}",
                database_type="mongodb"
            )
    
    async def get(self, entity_id: str) -> Optional[T]:
        try:
            collection = await self._get_collection()
            doc = await collection.find_one({"_id": entity_id})
            if doc is None:
                logger.debug(f"Document not found in {self._collection_name}: {entity_id}")
                return None
            return self._document_to_entity(doc)
        except Exception as e:
            logger.error(f"Failed to get document from {self._collection_name}: {e}")
            raise DatabaseError(
                message=f"Failed to get document: {str(e)}",
                database_type="mongodb"
            )
    
    async def update(self, entity_id: str, updates: Dict[str, Any]) -> Optional[T]:
        try:
            collection = await self._get_collection()
            updates["updated_at"] = datetime.now(timezone.utc)
            result = await collection.update_one(
                {"_id": entity_id},
                {"$set": updates}
            )
            if result.matched_count == 0:
                logger.warning(f"No document found to update in {self._collection_name}: {entity_id}")
                return None
            
            logger.debug(f"Updated document in {self._collection_name}: {entity_id}")
            return await self.get(entity_id)
        except Exception as e:
            logger.error(f"Failed to update document in {self._collection_name}: {e}")
            raise DatabaseError(
                message=f"Failed to update document: {str(e)}",
                database_type="mongodb"
            )
    
    async def delete(self, entity_id: str) -> bool:
        try:
            collection = await self._get_collection()
            result = await collection.delete_one({"_id": entity_id})
            if result.deleted_count > 0:
                logger.debug(f"Deleted document from {self._collection_name}: {entity_id}")
                return True
            logger.warning(f"No document found to delete in {self._collection_name}: {entity_id}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete document from {self._collection_name}: {e}")
            raise DatabaseError(
                message=f"Failed to delete document: {str(e)}",
                database_type="mongodb"
            )
    
    async def list(self, filters: Optional[Dict[str, Any]] = None, limit: int = 100, offset: int = 0) -> List[T]:
        try:
            collection = await self._get_collection()
            query = filters or {}
            cursor = collection.find(query).skip(offset).limit(limit)
            documents = await cursor.to_list(length=limit)
            return [self._document_to_entity(doc) for doc in documents]
        except Exception as e:
            logger.error(f"Failed to list documents from {self._collection_name}: {e}")
            raise DatabaseError(
                message=f"Failed to list documents: {str(e)}",
                database_type="mongodb"
            )
    
    def _entity_to_document(self, entity: T) -> Dict[str, Any]:
        if hasattr(entity, "model_dump"):
            doc = entity.model_dump()
        elif hasattr(entity, "dict"):
            doc = entity.dict()
        elif hasattr(entity, "__dict__"):
            doc = dict(entity.__dict__)
        else:
            raise DatabaseError(
                message="Entity must be serializable to dict",
                database_type="mongodb"
            )
        
        for id_field in ["id", "build_id", "failure_id"]:
            if id_field in doc:
                doc["_id"] = str(doc[id_field])
                break
        
        doc["created_at"] = doc.get("created_at", datetime.now(timezone.utc))
        doc["updated_at"] = datetime.now(timezone.utc)
        
        return doc
    
    def _document_to_entity(self, doc: Dict[str, Any]) -> T:
        raise NotImplementedError("Subclasses must implement _document_to_entity")


class BuildRepository(InMemoryRepository[BuildResult]):
    async def get_by_commit(self, commit_sha: str) -> List[BuildResult]:
        results = []
        for build in self._storage.values():
            if build.request and build.request.commit_sha == commit_sha:
                results.append(build)
        logger.debug(f"Found {len(results)} builds for commit {commit_sha[:8]}")
        return results
    
    async def get_by_status(self, status: BuildStatus) -> List[BuildResult]:
        results = [b for b in self._storage.values() if b.status == status]
        logger.debug(f"Found {len(results)} builds with status {status.value}")
        return results
    
    async def get_recent(self, limit: int = 50) -> List[BuildResult]:
        sorted_builds = sorted(
            self._storage.values(),
            key=lambda b: b.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )
        return sorted_builds[:limit]
    
    async def get_statistics(self, days: int = 7) -> Dict[str, Any]:
        cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        recent = [b for b in self._storage.values() 
                  if b.started_at and b.started_at >= cutoff]
        
        status_counts: Dict[str, int] = {}
        for build in recent:
            status = build.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        
        durations = [b.duration_seconds for b in recent if b.duration_seconds]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        
        total = max(len(recent), 1)
        success_count = status_counts.get("success", 0)
        
        return {
            "total_builds": len(recent),
            "status_distribution": status_counts,
            "average_duration_seconds": avg_duration,
            "success_rate": success_count / total,
        }


class FailureRepository(InMemoryRepository[FailureRecord]):
    async def get_by_signature(self, signature: str) -> List[FailureRecord]:
        results = [f for f in self._storage.values() if f.signature == signature]
        logger.debug(f"Found {len(results)} failures with signature {signature[:16]}")
        return results
    
    async def get_by_category(self, category: FailureCategory) -> List[FailureRecord]:
        results = [f for f in self._storage.values() if f.category == category]
        logger.debug(f"Found {len(results)} failures with category {category.value}")
        return results
    
    async def get_recent(self, limit: int = 50) -> List[FailureRecord]:
        sorted_failures = sorted(
            self._storage.values(),
            key=lambda f: f.created_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )
        return sorted_failures[:limit]
    
    async def get_most_common(self, limit: int = 10) -> List[Dict[str, Any]]:
        signature_counts: Dict[str, int] = {}
        signature_examples: Dict[str, FailureRecord] = {}
        
        for failure in self._storage.values():
            if failure.signature:
                signature_counts[failure.signature] = signature_counts.get(failure.signature, 0) + 1
                signature_examples[failure.signature] = failure
        
        sorted_sigs = sorted(signature_counts.items(), key=lambda x: x[1], reverse=True)
        
        return [
            {
                "signature": sig,
                "count": count,
                "category": signature_examples[sig].category.value,
                "example_message": str(signature_examples[sig].error_message)[:100],
            }
            for sig, count in sorted_sigs[:limit]
        ]
