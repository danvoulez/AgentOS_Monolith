# app/modules/delivery/repository.py  
# Repository for DeliverySession data operations

from typing import Optional, List, Dict, Any  
from app.core.logging_setup import logger  
from app.core.exceptions import RepositoryError  
from app.db.mongo_client import AsyncIOMotorDatabase  
from app.db.schemas.delivery_schemas import DeliverySessionDoc, DeliveryStatus, TrackingEventDoc \# Import models  
from app.db.schemas.common_schemas import PyObjectId  
from bson import ObjectId  
from motor.motor_asyncio import AsyncIOMotorCollection  
from pymongo import ReturnDocument  
from datetime import datetime, timezone, timedelta

class DeliveryRepository:  
    """Repository for DeliverySession data operations."""  
    _collection: AsyncIOMotorCollection

    def __init__(self, db: AsyncIOMotorDatabase):  
        self._collection \= db\["deliveries"\] \# Collection name  
        logger.debug("DeliveryRepository initialized.")  
        \# Indexes should be ensured by main app lifespan

    async def _map_doc(self, doc: Optional\[Dict\[str, Any\]\]) \-\> Optional\[DeliverySessionDoc\]:  
        if doc:  
            try: return DeliverySessionDoc.model_validate(doc) \# Pydantic V2  
            except Exception as e: logger.error(f"Failed to map document to DeliverySessionDoc: {e}"); return None  
        return None

    async def create_delivery(self, delivery_data: Dict\[str, Any\]) \-\> Optional\[DeliverySessionDoc\]:  
        """Creates a new delivery session document."""  
        log \= logger.bind(collection="deliveries", action="create")  
        log.debug("Creating new delivery document.")  
        try:  
            now \= datetime.now(timezone.utc)  
            delivery_data.setdefault("created_at", now)  
            delivery_data.setdefault("updated_at", now)  
            delivery_data.setdefault("current_status", DeliveryStatus.PENDING_ASSIGNMENT)  
            delivery_data.setdefault("tracking_history", \[\])

            result \= await self._collection.insert_one(delivery_data)  
            log.info(f"Delivery document created with ID: {result.inserted_id}")  
            created_doc \= await self._collection.find_one({"_id": result.inserted_id})  
            return await self._map_doc(created_doc)  
        except Exception as e:  
            log.exception("Database error creating delivery document.")  
            raise RepositoryError(f"Error creating delivery: {e}") from e

    async def get_delivery_by_id(self, delivery_id: str) \-\> Optional\[DeliverySessionDoc\]:  
        """Finds a delivery by its ObjectId string."""  
        if not ObjectId.is_valid(delivery_id): return None  
        try:  
            doc \= await self._collection.find_one({"_id": ObjectId(delivery_id)})  
            return await self._map_doc(doc)  
        except Exception as e:  
            logger.exception(f"Database error finding delivery by ID {delivery_id}.")  
            raise RepositoryError(f"Error fetching delivery by ID: {e}") from e

    async def update_delivery(self, delivery_id: str, update_data: Dict\[str, Any\]) \-\> Optional\[DeliverySessionDoc\]:  
        """Updates a delivery document by its ID using $set."""  
        if not ObjectId.is_valid(delivery_id): return None  
        if not update_data: return await self.get_delivery_by_id(delivery_id)

        update_data\["updated_at"\] \= datetime.now(timezone.utc)  
        log \= logger.bind(collection="deliveries", delivery_id=delivery_id, update_keys=list(update_data.keys()))  
        log.debug("Updating delivery document.")

        try:  
            updated_doc \= await self._collection.find_one_and_update(  
                {"_id": ObjectId(delivery_id)},  
                {"$set": update_data},  
                return_document=ReturnDocument.AFTER  
            )  
            if updated_doc: log.info("Delivery updated successfully.")  
            else: log.warning("Delivery not found for update.")  
            return await self._map_doc(updated_doc)  
        except Exception as e:  
            log.exception("Database error updating delivery document.")  
            raise RepositoryError(f"Error updating delivery: {e}") from e

    async def add_tracking_event(self, delivery_id: str, event: TrackingEventDoc, new_status: DeliveryStatus, location: Optional\[Dict\] \= None) \-\> Optional\[DeliverySessionDoc\]:  
         """Adds a tracking event and updates status/location atomically."""  
         if not ObjectId.is_valid(delivery_id): return None  
         log \= logger.bind(collection="deliveries", delivery_id=delivery_id, new_status=new_status.value)  
         log.info("Adding tracking event and updating status.")

         update_payload: Dict\[str, Any\] \= {  
             "$set": {  
                 "current_status": new_status.value,  
                 "updated_at": event.timestamp \# Use event timestamp for update  
             },  
             "$push": {  
                 "tracking_history": event.model_dump() \# Add validated event data  
             }  
         }  
         \# Conditionally update location  
         if location:  
              update_payload\["$set"\]\["current_location"\] \= location

         \# Set TTL expire_at field if delivery is reaching a final state  
         if new_status in \[DeliveryStatus.DELIVERED, DeliveryStatus.FAILED_DELIVERY, DeliveryStatus.CANCELLED, DeliveryStatus.RETURNED\]:  
             ttl_days \= getattr(settings, "DELIVERY_DOC_TTL_DAYS", 30\) \# Get TTL from config  
             expire_time \= event.timestamp \+ timedelta(days=ttl_days)  
             update_payload\["$set"\]\["expire_at"\] \= expire_time  
             log.info(f"Setting delivery expiration to {expire_time.isoformat()}")

         try:  
             updated_doc \= await self._collection.find_one_and_update(  
                 {"_id": ObjectId(delivery_id)},  
                 update_payload,  
                 return_document=ReturnDocument.AFTER  
             )  
             if updated_doc: log.success("Tracking event added and status updated.")  
             else: log.warning("Delivery not found for tracking update.")  
             return await self._map_doc(updated_doc)  
         except Exception as e:  
             log.exception("Database error adding tracking event.")  
             raise RepositoryError(f"Error adding tracking event: {e}") from e

    async def find_active_by_client(self, client_id: str, limit: int \= 10\) \-\> List\[DeliverySessionDoc\]:  
         """Finds active deliveries for a client."""  
         log \= logger.bind(collection="deliveries", client_id=client_id)  
         log.debug("Finding active deliveries by client.")  
         active_statuses \= \[s.value for s in DeliveryStatus if s not in \[DeliveryStatus.DELIVERED, DeliveryStatus.FAILED_DELIVERY, DeliveryStatus.CANCELLED, DeliveryStatus.RETURNED\]\]  
         query \= {"client_profile_id": client_id, "current_status": {"$in": active_statuses}}  
         try:  
             cursor \= self._collection.find(query).sort("created_at", \-1).limit(limit)  
             docs \= await cursor.to_list(length=limit)  
             mapped \= \[await self._map_doc(doc) for doc in docs\]  
             return \[item for item in mapped if item is not None\]  
         except Exception as e:  
              log.exception("Database error finding active deliveries by client.")  
              raise RepositoryError(f"Error fetching active deliveries: {e}") from e

    \# Add find_active_by_courier etc. if needed
