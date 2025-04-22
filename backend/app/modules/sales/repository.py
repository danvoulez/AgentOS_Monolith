# app/modules/sales/repository.py  
# Contains repositories for Sales, Products (within sales context if needed)

from typing import Optional, List, Dict, Any  
from app.core.logging_setup import logger  
from app.core.exceptions import RepositoryError \# Use generic repo error  
from app.db.mongo_client import AsyncIOMotorDatabase \# Direct type hint  
from app.db.schemas.sale_schemas import SaleDoc, SaleStatus, SaleItem \# Import Sale models  
from app.db.schemas.common_schemas import PyObjectId \# Import PyObjectId if used in models  
from bson import ObjectId  
from motor.motor_asyncio import AsyncIOMotorCollection \# Motor collection type  
from datetime import datetime, timedelta, timezone  
from pymongo import ReturnDocument \# Import for return_document

# Note: ProductRepository might live here or in a shared db.repositories location  
# For simplicity, let's assume a separate ProductRepository exists if complex logic needed.  
# If product logic is simple, methods could be directly in ProductService.  
# Let's focus on SaleRepository here.

class SaleRepository:  
    """Repository for Sale data operations."""  
    _collection: AsyncIOMotorCollection

    def __init__(self, db: AsyncIOMotorDatabase):  
        self._collection \= db\["sales"\] \# Use 'sales' collection name  
        logger.debug("SaleRepository initialized.")

    async def _map_doc(self, doc: Optional\[Dict\[str, Any\]\]) \-\> Optional\[SaleDoc\]:  
        """Maps MongoDB document to SaleDoc Pydantic model."""  
        if doc:  
            try:  
                return SaleDoc.model_validate(doc) \# Pydantic V2  
            except Exception as e:  
                logger.error(f"Failed to map document to SaleDoc: Doc={doc}, Error={e}")  
                return None  
        return None

    async def create_sale(self, sale_data: Dict\[str, Any\]) \-\> Optional\[SaleDoc\]:  
        """Creates a new sale document."""  
        log \= logger.bind(collection="sales", action="create")  
        log.debug(f"Creating new sale document.")  
        try:  
            \# Ensure timestamps and default status are set if not provided  
            now \= datetime.now(timezone.utc)  
            sale_data.setdefault("created_at", now)  
            sale_data.setdefault("updated_at", now)  
            sale_data.setdefault("status", SaleStatus.PROCESSING)  
            sale_data.setdefault("status_history", \[{"status": SaleStatus.PROCESSING.value, "timestamp": now.isoformat(), "actor": sale_data.get("agent_id", "system")}\])

            result \= await self._collection.insert_one(sale_data)  
            log.info(f"Sale document created with ID: {result.inserted_id}")  
            created_doc \= await self._collection.find_one({"_id": result.inserted_id})  
            return await self._map_doc(created_doc)  
        except Exception as e:  
            log.exception("Database error creating sale document.")  
            raise RepositoryError(f"Error creating sale: {e}") from e

    async def get_sale_by_id(self, sale_id: str) \-\> Optional\[SaleDoc\]:  
        """Finds a sale by its ObjectId string."""  
        log \= logger.bind(collection="sales", sale_id=sale_id)  
        log.debug("Finding sale by ID.")  
        if not ObjectId.is_valid(sale_id):  
            log.warning("Invalid ObjectId format provided.")  
            return None  
        try:  
            doc \= await self._collection.find_one({"_id": ObjectId(sale_id)})  
            return await self._map_doc(doc)  
        except Exception as e:  
            log.exception("Database error finding sale by ID.")  
            raise RepositoryError(f"Error fetching sale by ID: {e}") from e

    async def find_recent_by_agent_and_client(  
        self,  
        agent_id: str,  
        client_id: str,  
        time_window: timedelta  
    ) \-\> List\[SaleDoc\]:  
        """Finds sales for a specific agent and client within a recent time window."""  
        log \= logger.bind(collection="sales", agent_id=agent_id, client_id=client_id)  
        cutoff_time \= datetime.now(timezone.utc) \- time_window  
        log.debug(f"Finding recent sales since {cutoff_time.isoformat()}.")  
        query \= {  
            "agent_id": agent_id,  
            "client_id": client_id,  
            "created_at": {"$gte": cutoff_time},  
            \# Exclude potentially cancelled ones?  
            "status": {"$ne": SaleStatus.CANCELLED}  
        }  
        try:  
            cursor \= self._collection.find(query).sort("created_at", \-1)  
            docs \= await cursor.to_list(length=None) \# Get all recent matches  
            mapped_items \= \[await self._map_doc(doc) for doc in docs\]  
            return \[item for item in mapped_items if item is not None\]  
        except Exception as e:  
            log.exception("Database error finding recent sales.")  
            raise RepositoryError(f"Error fetching recent sales: {e}") from e

    async def update_sale_status(  
            self, sale_id: str, new_status: SaleStatus, status_history_entry: Dict\[str, Any\]  
        ) \-\> Optional\[SaleDoc\]:  
        """Updates the status and status history of a sale."""  
        log \= logger.bind(collection="sales", sale_id=sale_id, new_status=new_status.value)  
        log.info("Updating sale status in repository.")  
        if not ObjectId.is_valid(sale_id):  
            log.warning("Invalid ObjectId format for sale status update.")  
            return None  
        try:  
            updated_doc \= await self._collection.find_one_and_update(  
                {"_id": ObjectId(sale_id)},  
                {  
                    "$set": {  
                        "status": new_status.value, \# Store enum value as string  
                        "updated_at": datetime.now(timezone.utc)  
                    },  
                    "$push": { "status_history": status_history_entry }  
                },  
                return_document=ReturnDocument.AFTER \# Use constant from pymongo  
            )  
            return await self._map_doc(updated_doc) \# Returns None if not found  
        except Exception as e:  
            log.exception("Database error updating sale status.")  
            raise RepositoryError(f"Error updating sale status: {e}") from e

    \# Add other methods like list_sales_by_client, etc. as needed  
    async def list_sales(  
        self,  
        client_id: Optional\[str\] \= None,  
        agent_id: Optional\[str\] \= None,  
        status: Optional\[SaleStatus\] \= None,  
        skip: int \= 0,  
        limit: int \= 20  
    ) \-\> List\[SaleDoc\]:  
        """Lists sales with optional filters."""  
        query: Dict\[str, Any\] \= {}  
        if client_id: query\["client_id"\] \= client_id  
        if agent_id: query\["agent_id"\] \= agent_id  
        if status: query\["status"\] \= status.value

        log \= logger.bind(collection="sales", filter=query, skip=skip, limit=limit)  
        log.debug("Listing sales.")  
        try:  
            cursor \= self._collection.find(query).sort("created_at", \-1).skip(skip).limit(limit)  
            docs \= await cursor.to_list(length=limit)  
            mapped \= \[await self._map_doc(doc) for doc in docs\]  
            return \[item for item in mapped if item is not None\]  
        except Exception as e:  
            log.exception("Database error listing sales.")  
            raise RepositoryError(f"Error listing sales: {e}") from e
