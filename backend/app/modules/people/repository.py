# app/modules/people/repository.py  
# Contains repositories for People (Profiles) and potentially Users (if managed here)

from typing import Optional, List, Dict, Any  
from app.core.logging_setup import logger  
from app.core.exceptions import RepositoryError  
from app.db.mongo_client import AsyncIOMotorDatabase  
from app.db.schemas.people_schemas import ProfileDoc \# Import Profile model  
from app.db.schemas.common_schemas import PyObjectId  
from bson import ObjectId  
from motor.motor_asyncio import AsyncIOMotorCollection  
from pymongo.errors import DuplicateKeyError  
from datetime import datetime, timezone

class PeopleRepository:  
    """Repository for Profile data operations."""  
    _collection: AsyncIOMotorCollection

    def __init__(self, db: AsyncIOMotorDatabase):  
        \# Ensure db is passed correctly if using Depends elsewhere  
        self._collection \= db\["profiles"\] \# Use 'profiles' collection  
        logger.debug("PeopleRepository initialized.")  
        \# Consider ensuring indexes here if not done in main lifespan  
        \# asyncio.create_task(self._ensure_indexes())

    async def _ensure_indexes(self):  
        """Creates necessary indexes if they don't exist."""  
        \# Called once on init maybe? Or rely on main.py lifespan  
        try:  
            await self._collection.create_index("user_id", sparse=True, background=True)  
            await self._collection.create_index("external_id", sparse=True, background=True)  
            await self._collection.create_index("whatsapp_id", unique=True, sparse=True, background=True)  
            await self._collection.create_index("email", unique=True, sparse=True, background=True)  
            await self._collection.create_index("phone_number", sparse=True, background=True)  
            await self._collection.create_index("roles", background=True)  
            await self._collection.create_index("is_active", background=True)  
            logger.info("Indexes checked/created for 'profiles' collection.")  
        except Exception as e:  
            logger.exception("Error ensuring indexes for 'profiles' collection.")

    async def _map_doc(self, doc: Optional\[Dict\[str, Any\]\]) \-\> Optional\[ProfileDoc\]:  
        """Maps MongoDB document to ProfileDoc Pydantic model."""  
        if doc:  
            try: return ProfileDoc.model_validate(doc) \# Pydantic V2  
            except Exception as e: logger.error(f"Failed to map document to ProfileDoc: {e}"); return None  
        return None

    async def create_profile(self, profile_data: Dict\[str, Any\]) \-\> Optional\[ProfileDoc\]:  
        """Creates a new profile document."""  
        log \= logger.bind(collection="profiles", action="create")  
        log.debug("Creating new profile document.")  
        try:  
            now \= datetime.now(timezone.utc)  
            profile_data.setdefault("created_at", now)  
            profile_data.setdefault("updated_at", now)  
            profile_data.setdefault("is_active", True)  
            profile_data.setdefault("roles", \[\])  
            profile_data.setdefault("metadata", {})  
            \# Ensure full_name is derived if possible  
            if not profile_data.get("full_name") and profile_data.get("first_name"):  
                 profile_data\["full_name"\] \= f"{profile_data\['first_name'\]} {profile_data.get('last_name', '')}".strip()

            result \= await self._collection.insert_one(profile_data)  
            log.info(f"Profile document created with ID: {result.inserted_id}")  
            created_doc \= await self._collection.find_one({"_id": result.inserted_id})  
            return await self._map_doc(created_doc)  
        except DuplicateKeyError as e:  
            \# Determine which field caused the duplicate error  
            field \= "unknown"  
            if "email" in str(e): field \= "email"  
            elif "whatsapp_id" in str(e): field \= "whatsapp_id"  
            elif "user_id" in str(e): field \= "user_id"  
            log.warning(f"Profile creation failed: Duplicate key for field '{field}'.")  
            \# Re-raise specific error for service layer  
            raise DuplicateKeyError(f"Duplicate key error for field '{field}'") from e  
        except Exception as e:  
            log.exception("Database error creating profile document.")  
            raise RepositoryError(f"Error creating profile: {e}") from e

    async def get_profile_by_id(self, profile_id: str) \-\> Optional\[ProfileDoc\]:  
        """Finds a profile by its ObjectId string."""  
        if not ObjectId.is_valid(profile_id): return None  
        try:  
            doc \= await self._collection.find_one({"_id": ObjectId(profile_id)})  
            return await self._map_doc(doc)  
        except Exception as e:  
            logger.exception(f"Database error finding profile by ID {profile_id}.")  
            raise RepositoryError(f"Error fetching profile by ID: {e}") from e

    async def get_profile_by_identifier(self, identifier: str, field: str \= "email") \-\> Optional\[ProfileDoc\]:  
        """Finds a profile by a specific identifier field (email, whatsapp_id, user_id, external_id)."""  
        allowed_fields \= \["email", "whatsapp_id", "user_id", "external_id"\]  
        if field not in allowed_fields:  
            raise ValueError(f"Invalid identifier field specified: {field}")  
        log \= logger.bind(collection="profiles", field=field, identifier=identifier)  
        log.debug("Finding profile by identifier.")  
        try:  
            doc \= await self._collection.find_one({field: identifier})  
            return await self._map_doc(doc)  
        except Exception as e:  
            log.exception(f"Database error finding profile by {field}.")  
            raise RepositoryError(f"Error fetching profile by {field}: {e}") from e

    async def update_profile(self, profile_id: str, update_data: Dict\[str, Any\]) \-\> Optional\[ProfileDoc\]:  
        """Updates a profile document by its ID."""  
        log \= logger.bind(collection="profiles", profile_id=profile_id)  
        log.debug("Updating profile document.")  
        if not ObjectId.is_valid(profile_id): return None  
        if not update_data: return await self.get_profile_by_id(profile_id)

        update_data\["updated_at"\] \= datetime.now(timezone.utc)  
        \# Re-derive full_name if first/last name changed  
        if "first_name" in update_data or "last_name" in update_data:  
             \# Need existing doc to get potentially unchanged parts of name  
             \# This logic is better placed in the service layer before calling repo update  
             pass \# Service should handle full_name derivation

        try:  
            updated_doc \= await self._collection.find_one_and_update(  
                {"_id": ObjectId(profile_id)},  
                {"$set": update_data},  
                return_document=ReturnDocument.AFTER  
            )  
            if updated_doc: log.info("Profile updated successfully.")  
            else: log.warning("Profile not found for update.")  
            return await self._map_doc(updated_doc)  
        except DuplicateKeyError as e:  
             field \= "email" if "email" in str(e) else "whatsapp_id" if "whatsapp_id" in str(e) else "user_id" if "user_id" in str(e) else "unknown"  
             log.warning(f"Profile update failed: Duplicate key for '{field}'.")  
             raise DuplicateKeyError(f"Duplicate key error for field '{field}'") from e  
        except Exception as e:  
            log.exception("Database error updating profile document.")  
            raise RepositoryError(f"Error updating profile: {e}") from e

    async def add_role(self, profile_id: str, role: str) \-\> bool:  
        """Adds a role to a profile's roles array if it doesn't exist."""  
        if not ObjectId.is_valid(profile_id): return False  
        try:  
            result \= await self._collection.update_one(  
                {"_id": ObjectId(profile_id)},  
                {"$addToSet": {"roles": role}, "$set": {"updated_at": datetime.now(timezone.utc)}}  
            )  
            return result.matched_count \> 0 \# True if profile found, regardless if role was added or existed  
        except Exception as e:  
             logger.exception(f"Error adding role '{role}' to profile {profile_id}.")  
             raise RepositoryError(f"Error adding role: {e}") from e

    async def remove_role(self, profile_id: str, role: str) \-\> bool:  
        """Removes a role from a profile's roles array."""  
        if not ObjectId.is_valid(profile_id): return False  
        try:  
            result \= await self._collection.update_one(  
                {"_id": ObjectId(profile_id)},  
                {"$pull": {"roles": role}, "$set": {"updated_at": datetime.now(timezone.utc)}}  
            )  
            \# Returns True if profile found, even if role wasn't present to be removed  
            return result.matched_count \> 0  
        except Exception as e:  
             logger.exception(f"Error removing role '{role}' from profile {profile_id}.")  
             raise RepositoryError(f"Error removing role: {e}") from e

    \# Add list/count methods if needed  
    async def list_profiles(self, query: Optional\[Dict\[str, Any\]\] \= None, skip: int \= 0, limit: int \= 100\) \-\> List\[ProfileDoc\]:  
         """Lists profiles based on a query."""  
         if query is None: query \= {}  
         try:  
             cursor \= self._collection.find(query).sort("created_at", \-1).skip(skip).limit(limit)  
             docs \= await cursor.to_list(length=limit)  
             mapped \= \[await self._map_doc(doc) for doc in docs\]  
             return \[item for item in mapped if item is not None\]  
         except Exception as e:  
              logger.exception("Database error listing profiles.")  
              raise RepositoryError(f"Error listing profiles: {e}") from e
