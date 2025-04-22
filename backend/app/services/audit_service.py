# app/services/audit_service.py  
# Service responsible for writing audit logs to MongoDB

from typing import Dict, Any, Optional  
from app.core.config import settings  
from app.core.logging_config import logger  
from app.db.mongo_client import get_database \# Import DB client  
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection  
from datetime import datetime, timezone

class AuditService:  
    """Logs important actions and events to a dedicated MongoDB collection."""  
    def __init__(self):  
        self._db: Optional\[AsyncIOMotorDatabase\] \= None  
        self._collection: Optional\[AsyncIOMotorCollection\] \= None  
        self.enabled \= settings.AUDIT_LOG_ENABLED  
        self.collection_name \= settings.AUDIT_LOG_MONGO_COLLECTION  
        logger.info(f"AuditService initialized. Enabled: {self.enabled}")

    async def _get_collection(self) \-\> Optional\[AsyncIOMotorCollection\]:  
        """Lazy initializes DB connection and collection."""  
        if not self.enabled: return None  
        if self._collection is None:  
            try:  
                 self._db \= get_database()  
                 self._collection \= self._db\[self.collection_name\]  
                 \# Ensure TTL index exists for automatic cleanup (optional)  
                 \# await self._collection.create_index("timestamp", expireAfterSeconds=...)  
            except RuntimeError as e:  
                 logger.error(f"AuditService failed to get DB collection: {e}")  
                 self._collection \= None \# Prevent further attempts if connection fails  
                 self.enabled \= False \# Disable if DB fails  
        return self._collection

    async def log_event(  
        self,  
        actor_id: str, \# User, Agent, or System ID performing the action  
        action: str, \# Verb describing the action (e.g., "create_sale", "login_failed", "update_stock")  
        entity_type: Optional\[str\] \= None, \# Type of entity affected (e.g., "sale", "product", "user")  
        entity_id: Optional\[str\] \= None, \# ID of the entity affected  
        success: bool \= True, \# Whether the action succeeded  
        details: Optional\[Dict\[str, Any\]\] \= None, \# Additional context (e.g., parameters, error message)  
        trace_id: Optional\[str\] \= None \# Trace ID for request correlation  
    ):  
        """Writes an audit log entry to MongoDB."""  
        collection \= await self._get_collection()  
        if not collection: return \# Logging disabled or DB unavailable

        log_entry \= {  
            "timestamp": datetime.now(timezone.utc),  
            "actor_id": actor_id,  
            "action": action,  
            "entity_type": entity_type,  
            "entity_id": entity_id,  
            "success": success,  
            "details": details or {},  
            "trace_id": trace_id or "N/A"  
        }  
        log \= logger.bind(audit_action=action, audit_actor=actor_id, audit_success=success)  
        try:  
            await collection.insert_one(log_entry)  
            log.debug("Audit event logged successfully.")  
        except Exception as e:  
            log.exception("Failed to write audit log to MongoDB.")  
            \# Don't fail the original request due to audit log failure

# Singleton instance (or inject via FastAPI Depends)  
audit_service \= AuditService()

# \--- Example Usage \---  
# await audit_service.log_event(  
#     actor_id=current_user.user_id,  
#     action="create_sale",  
#     entity_type="sale",  
#     entity_id=str(created_sale.id),  
#     success=True,  
#     details={"total_amount": created_sale.total_amount, "item_count": len(created_sale.items)},  
#     trace_id=trace_id_var.get()  
# )  
