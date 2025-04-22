# app/services/memory_service.py
from typing import List, Optional, Dict, Any, Tuple
from app.core.config import settings
from app.core.logging_config import logger
from app.db.schemas.memory_schemas import ChatMessageDoc # Import the memory schema
from app.core.redis_client import get_redis_client, redis # Import Redis client
from app.db.mongo_client import get_database # Import DB client
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection
from app.services.embedding_service import generate_embedding # Import embedding function
from app.core.exceptions import LLMError # Assuming this is defined
import json
from datetime import datetime, timezone
from bson import ObjectId # Import ObjectId

class HybridMemory:
    """
    Manages memory for a specific chat session, interacting with Redis and MongoDB.
    Instantiated by MemoryService for a given chat_id.
    """
    def __init__(
        self,
        chat_id: str,
        user_id: Optional[str],
        redis_client: Optional[redis.Redis], # Redis client is optional now
        mongo_collection: AsyncIOMotorCollection # Mongo collection is required
    ):
        if not chat_id: raise ValueError("chat_id is required for HybridMemory")
        self.chat_id = chat_id
        self.user_id = user_id
        self._redis = redis_client # Can be None if cache disabled or connection failed
        self._mongo_coll = mongo_collection
        self.redis_key = f"{settings.MEMORY_REDIS_KEY_PREFIX}{self.chat_id}"
        self.max_redis_history = settings.MEMORY_REDIS_MAX_HISTORY
        self.redis_ttl = settings.MEMORY_REDIS_TTL_SECONDS
        self.log = logger.bind(chat_id=chat_id, user_id=user_id or "N/A", service="HybridMemory")
        self.log.debug("HybridMemory instance created.")

    async def add_message(self, message_data: Dict[str, Any]) -> Optional[ChatMessageDoc]:
        """Adds a message to MongoDB and then caches in Redis if enabled."""
        self.log.info(f"Adding message. Role: {message_data.get('role')}, Type: {message_data.get('type')}")

        # 1. Prepare document for MongoDB
        message_data["chat_id"] = self.chat_id
        if self.user_id: message_data["user_id"] = self.user_id
        message_data.setdefault("timestamp", datetime.now(timezone.utc))

        # TODO: Implement PII Masking if settings.MEMORY_MASK_PII is True
        if settings.MEMORY_MASK_PII:
            # message_data['content'] = mask_pii(message_data.get('content', ''))
            message_data['is_pii_masked'] = True
            self.log.warning("PII Masking enabled but not implemented.")

        # 2. Validate and prepare document object
        try:
            # Exclude potential '_id' if retrying, let Mongo generate it
            message_data.pop('_id', None)
            message_doc_validated = ChatMessageDoc.model_validate(message_data)
            doc_to_insert = message_doc_validated.model_dump(by_alias=True, exclude={'id'}) # Use model_dump for Pydantic v2
        except Exception as e:
             self.log.error(f"Failed to validate message data before insert: {e}")
             return None

        # 3. Optional: Generate embedding
        if settings.STORE_AGENT_EMBEDDINGS and doc_to_insert.get('type') == 'text' and doc_to_insert.get('content'):
            try:
                embedding = await generate_embedding(doc_to_insert['content'])
                if embedding:
                    doc_to_insert['embedding'] = embedding
                    doc_to_insert['embedding_model'] = settings.OPENAI_EMBEDDING_MODEL
                    self.log.debug("Embedding generated for message.")
            except Exception as e:
                 self.log.exception("Failed to generate embedding for message.")
                 # Decide: Fail insert or continue without embedding? Continue for now.

        # 4. Insert into MongoDB
        inserted_id: Optional[ObjectId] = None
        try:
            result = await self._mongo_coll.insert_one(doc_to_insert)
            inserted_id = result.inserted_id
            self.log.info(f"Message persisted to MongoDB. ID: {inserted_id}")
        except Exception as e:
            self.log.exception("Failed to persist message to MongoDB.")
            return None # Fail operation if DB insert fails

        # 5. Add to Redis Cache (if enabled and Mongo succeeded)
        if settings.MEMORY_CACHE_ENABLED and self._redis and inserted_id:
            try:
                # Re-create the full Pydantic model with the ID for caching
                # This ensures the cached version matches the DB representation
                final_doc_for_cache = ChatMessageDoc(id=inserted_id, **doc_to_insert)
                message_json = final_doc_for_cache.model_dump_json(by_alias=True)

                pipe = self._redis.pipeline()
                pipe.lpush(self.redis_key, message_json)
                pipe.ltrim(self.redis_key, 0, self.max_redis_history - 1)
                pipe.expire(self.redis_key, self.redis_ttl)
                await pipe.execute()
                self.log.debug("Message added to Redis cache.")
                return final_doc_for_cache # Return the full object with ID
            except Exception as e:
                self.log.exception("Failed to add message to Redis cache (Mongo save was successful).")
                # Return the object even if caching failed
                return ChatMessageDoc(id=inserted_id, **doc_to_insert) if inserted_id else None

        # Return the object if cache disabled or failed, but Mongo succeeded
        return ChatMessageDoc(id=inserted_id, **doc_to_insert) if inserted_id else None

    async def get_recent_messages(self, limit: int = 10) -> List[ChatMessageDoc]:
        """Gets recent messages, trying Redis first."""
        if limit <= 0: return []
        self.log.debug(f"Getting recent messages (limit={limit}).")

        # 1. Try Redis Cache
        if settings.MEMORY_CACHE_ENABLED and self._redis:
            try:
                raw_history = await self._redis.lrange(self.redis_key, 0, limit - 1)
                if raw_history:
                    messages: List[ChatMessageDoc] = []
                    for item in raw_history:
                        try: messages.append(ChatMessageDoc.model_validate_json(item)) # Pydantic v2
                        except Exception as parse_error: self.log.error(f"Failed to parse message from Redis cache: {parse_error}")
                    messages.reverse() # Chronological order
                    self.log.info(f"Retrieved {len(messages)} messages from Redis cache.")
                    # Touch TTL on successful cache read?
                    # await self._redis.expire(self.redis_key, self.redis_ttl)
                    return messages
                else: self.log.info("Redis cache miss or empty.")
            except Exception as e:
                 self.log.exception("Error getting messages from Redis cache. Falling back to DB.")

        # 2. Fallback to MongoDB
        self.log.info("Fetching recent messages from MongoDB.")
        try:
            cursor = self._mongo_coll.find(
                {"chat_id": self.chat_id, "is_forgotten": {"$ne": True}}
            ).sort("timestamp", -1).limit(limit) # Get newest first
            docs = await cursor.to_list(length=limit)
            messages = []
            for doc in docs:
                 try: messages.append(ChatMessageDoc.model_validate(doc)) # Pydantic v2
                 except Exception as map_error: self.log.error(f"Failed to map message from MongoDB: {map_error}")
            messages.reverse() # Chronological order
            self.log.info(f"Retrieved {len(messages)} messages from MongoDB.")
            # TODO: Optional: Repopulate cache?
            return messages
        except Exception as e:
            self.log.exception("Error fetching messages from MongoDB.")
            return []

    async def get_relevant_memory(self, query_text: str, k: int = 5) -> List[ChatMessageDoc]:
        """Finds relevant messages using vector search (if enabled)."""
        self.log.debug(f"Searching relevant memory for query (k={k}).")
        if not settings.AGENT_USE_VECTOR_MEMORY or not settings.STORE_AGENT_EMBEDDINGS:
            self.log.warning("Vector search requested but not enabled in settings.")
            return []
        if not query_text: return []

        query_embedding = await generate_embedding(query_text)
        if not query_embedding:
            self.log.error("Failed to generate embedding for relevance search query.")
            return []

        try:
            pipeline = [
                {'$vectorSearch': {
                    'index': settings.ATLAS_VECTOR_INDEX_NAME,
                    'path': 'embedding',
                    'queryVector': query_embedding,
                    'numCandidates': settings.ATLAS_VECTOR_NUM_CANDIDATES,
                    'limit': k,
                    'filter': {'chat_id': self.chat_id, 'is_forgotten': {'$ne': True}}
                }},
                {'$project': {
                    '_id': 1, 'chat_id': 1, 'user_id': 1, 'timestamp': 1, 'role': 1,
                    'type': 1, 'content': 1, 'is_pii_masked': 1, 'tool_name': 1, # Add fields
                    'score': { '$meta': 'vectorSearchScore' }
                }},
                { '$sort': { 'timestamp': 1 } } # Optional: Chronological order of results
            ]
            results_cursor = self._mongo_coll.aggregate(pipeline)
            docs = await results_cursor.to_list(length=k)

            memories: List[ChatMessageDoc] = []
            for doc in docs:
                 self.log.debug(f"Relevant memory found: Score={doc.get('score', 'N/A')}, Content='{doc.get('content', '')[:50]}...'")
                 try: memories.append(ChatMessageDoc.model_validate(doc))
                 except Exception as map_error: self.log.error(f"Failed to map vector search result document: {map_error}")

            self.log.info(f"Retrieved {len(memories)} relevant memories via vector search.")
            return memories
        except Exception as e:
            self.log.exception("Error during vector search query.")
            return []

    async def forget_message(self, message_id: str) -> bool:
        """Marks a specific message as 'forgotten' (soft delete)."""
        self.log.info(f"Forgetting message ID: {message_id}")
        if not ObjectId.is_valid(message_id): return False
        try:
            result = await self._mongo_coll.update_one(
                {"_id": ObjectId(message_id), "chat_id": self.chat_id},
                {"$set": {"is_forgotten": True, "updated_at": datetime.now(timezone.utc)}}
            )
            if result.matched_count > 0:
                self.log.success("Message marked as forgotten in MongoDB.")
                # TODO: Remove from Redis cache? Complex. Easier to let TTL expire it.
                return True
            else:
                self.log.warning("Message not found or already forgotten.")
                return False
        except Exception as e:
            self.log.exception("Error forgetting message in MongoDB.")
            return False

    async def update_feedback(self, message_id: str, score: Optional[int] = None, flagged: Optional[bool] = None, reason: Optional[str] = None) -> bool:
        """Updates feedback fields for a message."""
        self.log.info(f"Updating feedback for message ID: {message_id}")
        if not ObjectId.is_valid(message_id): return False

        update_fields = {"updated_at": datetime.now(timezone.utc)}
        if score is not None: update_fields["feedback_score"] = score
        if flagged is not None: update_fields["is_flagged"] = flagged
        if flagged and reason: update_fields["flagged_reason"] = reason
        elif flagged is False: update_fields["flagged_reason"] = None

        if len(update_fields) == 1: return False # No actual feedback provided

        try:
            result = await self._mongo_coll.update_one(
                {"_id": ObjectId(message_id), "chat_id": self.chat_id},
                {"$set": update_fields}
            )
            if result.matched_count > 0:
                self.log.success("Feedback updated successfully.")
                return True
            else:
                self.log.warning("Message not found for feedback update.")
                return False
        except Exception as e:
             self.log.exception("Error updating feedback in MongoDB.")
             return False

# --- Memory Service (Factory/Manager) ---
class MemoryService:
    """Provides instances of HybridMemory for specific chats."""
    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._mongo_coll: Optional[AsyncIOMotorCollection] = None
        logger.debug("MemoryService initialized.")

    async def _get_clients(self) -> Tuple[Optional[redis.Redis], Optional[AsyncIOMotorCollection]]:
        """Lazy initializes and returns Redis client and Mongo collection."""
        if self._redis is None and settings.MEMORY_CACHE_ENABLED:
             try: self._redis = get_redis_client()
             except RuntimeError: self._redis = None; logger.error("MemoryService failed to get Redis client.")

        if self._mongo_coll is None:
             try:
                  self._db = get_database()
                  self._mongo_coll = self._db[settings.MEMORY_MONGO_COLLECTION]
                  # Ensure indexes on first access? Or rely on lifespan? Lifespan preferred.
             except RuntimeError:
                  self._mongo_coll = None; logger.error("MemoryService failed to get Mongo collection.")

        return self._redis, self._mongo_coll

    async def get_memory_for_chat(self, chat_id: str, user_id: Optional[str] = None) -> HybridMemory:
        """Gets a HybridMemory instance ready for a specific chat."""
        redis_client, mongo_collection = await self._get_clients()
        if mongo_collection is None: # Mongo is essential
             raise RuntimeError("MongoDB connection unavailable for memory service.")
        if redis_client is None and settings.MEMORY_CACHE_ENABLED:
             logger.warning(f"Redis cache unavailable for chat {chat_id}, proceeding with DB only.")

        return HybridMemory(
            chat_id=chat_id,
            user_id=user_id,
            redis_client=redis_client, # Can be None
            mongo_collection=mongo_collection
        )

# Singleton instance (or inject via FastAPI Depends)
memory_service = MemoryService()

# Dependency for FastAPI endpoints
async def get_memory_service() -> MemoryService:
    # Can add readiness check here if needed
    return memory_service
