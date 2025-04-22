# app/services/notification_service.py  
# Publishes events to Redis for WebSocket broadcasting or inter-service communication

from app.core.logging_config import logger  
from app.core.redis_client import get_redis_client, redis \# Use unified client  
from app.core.config import settings \# Get channel names  
import json  
from typing import Dict, Any, Optional

class NotificationService:  
    """Service to publish messages to Redis Pub/Sub channels."""  
    def __init__(self):  
        self._redis: Optional\[redis.Redis\] \= None  
        self.log \= logger.bind(service="NotificationService")  
        self.log.debug("NotificationService initialized.")

    async def _get_redis(self) \-\> Optional\[redis.Redis\]:  
        if self._redis is None:  
            try: self._redis \= get_redis_client()  
            except RuntimeError as e: self._redis \= None; self.log.error(f"Redis client error: {e}")  
        return self._redis

    async def publish(self, channel: str, payload: Dict\[str, Any\]):  
        """Publishes a dictionary payload to a specific Redis channel."""  
        redis_client \= await self._get_redis()  
        if not redis_client:  
            self.log.error(f"Cannot publish to channel '{channel}': Redis client unavailable.")  
            return False \# Indicate failure

        log \= self.log.bind(channel=channel)  
        try:  
            \# Serialize payload to JSON (handle non-serializable types)  
            message_json \= json.dumps(payload, default=str)  
            await redis_client.publish(channel, message_json)  
            log.info(f"Published event. Payload keys: {list(payload.keys())}")  
            return True  
        except TypeError as e:  
             log.error(f"Cannot publish: Payload not JSON serializable. Error: {e}. Payload Snippet: {str(payload)\[:200\]}")  
             return False  
        except redis.ConnectionError as e:  
             log.error(f"Redis connection error during publish: {e}")  
             return False  
        except Exception:  
            log.exception(f"Failed to publish event to channel '{channel}'.")  
            return False

    \# \--- Helper methods for specific event types \---

    async def publish_websocket_update(self, target: str, target_id: str, event_type: str, data: Dict\[str, Any\]):  
        """Publishes an update meant for WebSocket broadcast."""  
        \# Target can be 'all', 'user', 'chat', 'courier' etc.  
        \# The Redis listener in websocket/redis_listener.py will handle routing based on this  
        channel \= settings.BACKEND_PUBLISH_EVENT_CHANNEL \# Use a general channel for WS updates  
        payload \= {  
            "__target__": target, \# "all", "user", "group", "client_id" etc.  
            "__target_id__": target_id, \# User ID, Group ID, Chat ID etc.  
            "event_type": event_type, \# e.g., "delivery_status_update", "new_suggestion"  
            "data": data \# The actual data payload for the frontend  
        }  
        await self.publish(channel, payload)

    async def publish_audit_log(self, actor_id: str, action: str, entity_type: Optional\[str\]=None, entity_id: Optional\[str\]=None, success: bool \= True, details: Optional\[Dict\]=None):  
         """Publishes an event for the AuditService to log."""  
         channel \= "system.audit" \# Specific channel for audit events  
         payload \= {  
             "event_type": "audit_log_request",  
             "actor_id": actor_id,  
             "action": action,  
             "entity_type": entity_type,  
             "entity_id": entity_id,  
             "success": success,  
             "details": details or {}  
         }  
         await self.publish(channel, payload)

# Singleton instance (or inject via FastAPI Depends)  
notification_service \= NotificationService()
