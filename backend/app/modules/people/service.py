# app/modules/people/service.py  
# Service layer for Profile logic (formerly agentos-pessoas)

from typing import Optional, List, Dict, Any  
from fastapi import Depends, HTTPException, status  
from .repository import PeopleRepository  
from app.db.schemas.people_schemas import ProfileDoc, ProfileCreate, ProfileUpdate  
from app.core.logging_setup import logger  
from app.core.exceptions import RepositoryError  
from pymongo.errors import DuplicateKeyError  
from .exceptions import ProfileNotFoundError, DuplicateProfileError \# Import custom exceptions

class PeopleService:  
    """Service layer for managing user profiles."""  
    def __init__(self, people_repo: PeopleRepository \= Depends()):  
        self.people_repo \= people_repo  
        logger.debug("PeopleService initialized.")

    async def create_profile(self, profile_in: ProfileCreate) \-\> ProfileDoc:  
        """Creates a new profile."""  
        log \= logger.bind(email=profile_in.email, wa_id=profile_in.whatsapp_id)  
        log.info("Creating new profile via service.")

        \# Prepare data, derive full_name  
        profile_data \= profile_in.model_dump(exclude_unset=True)  
        if profile_in.first_name:  
             profile_data\["full_name"\] \= f"{profile_in.first_name} {profile_in.last_name or ''}".strip()

        try:  
            created_profile \= await self.people_repo.create_profile(profile_data)  
            if not created_profile: \# Should not happen if repo raises correctly  
                 raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Profile creation failed unexpectedly after DB call.")  
            log.success(f"Profile created successfully: {created_profile.id}")  
            return created_profile  
        except DuplicateKeyError as e:  
             field \= "email" if "email" in str(e) else "whatsapp_id" if "whatsapp_id" in str(e) else "user_id" if "user_id" in str(e) else "identifier"  
             log.warning(f"Duplicate profile detected for {field}.")  
             raise DuplicateProfileError(field=field, value=profile_data.get(field)) \# Raise domain error  
        except RepositoryError as e:  
             log.exception("Repository error during profile creation.")  
             raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Database error: {e}")  
        except Exception as e:  
            log.exception("Unexpected error during profile creation.")  
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    async def get_profile_by_id(self, profile_id: str) \-\> ProfileDoc:  
        """Gets a profile by its internal MongoDB ID."""  
        log \= logger.bind(profile_id=profile_id)  
        log.debug("Getting profile by ID via service.")  
        try:  
            profile \= await self.people_repo.get_profile_by_id(profile_id)  
            if not profile:  
                 raise ProfileNotFoundError(identifier=profile_id)  
            return profile  
        except ProfileNotFoundError as e:  
            log.warning(f"Profile not found: {e}")  
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))  
        except RepositoryError as e:  
             log.exception("Repository error getting profile by ID.")  
             raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Database error: {e}")  
        except Exception as e:  
            log.exception("Unexpected error getting profile by ID.")  
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    async def find_profile(  
        self,  
        user_id: Optional\[str\] \= None,  
        email: Optional\[str\] \= None,  
        whatsapp_id: Optional\[str\] \= None,  
        external_id: Optional\[str\] \= None  
    ) \-\> Optional\[ProfileDoc\]:  
        """Finds a profile based on the first provided identifier."""  
        log \= logger.bind(user_id=user_id, email=email, wa_id=whatsapp_id, ext_id=external_id)  
        log.debug("Finding profile by identifier via service.")  
        try:  
            if user_id: return await self.people_repo.get_profile_by_identifier(user_id, "user_id")  
            if email: return await self.people_repo.get_profile_by_identifier(email, "email")  
            if whatsapp_id: return await self.people_repo.get_profile_by_identifier(whatsapp_id, "whatsapp_id")  
            if external_id: return await self.people_repo.get_profile_by_identifier(external_id, "external_id")  
            log.warning("No identifier provided to find profile.")  
            return None  
        except RepositoryError as e:  
             log.exception("Repository error finding profile.")  
             \# Don't raise 503 here, maybe just return None or log? Return None.  
             return None  
        except Exception as e:  
            log.exception("Unexpected error finding profile.")  
            return None

    async def update_profile(self, profile_id: str, profile_in: ProfileUpdate) \-\> ProfileDoc:  
        """Updates an existing profile."""  
        log \= logger.bind(profile_id=profile_id)  
        log.info("Updating profile via service.")

        update_data \= profile_in.model_dump(exclude_unset=True)  
        if not update_data:  
            log.warning("Update called with no data.")  
            return await self.get_profile_by_id(profile_id) \# Return current if no changes

        \# Logic to derive full_name if names are changing  
        if "first_name" in update_data or "last_name" in update_data:  
             \# Fetch existing to combine names correctly  
             existing_profile \= await self.people_repo.get_profile_by_id(profile_id)  
             if existing_profile:  
                  first \= update_data.get("first_name", existing_profile.first_name)  
                  last \= update_data.get("last_name", existing_profile.last_name)  
                  if first: update_data\["full_name"\] \= f"{first} {last or ''}".strip()  
                  elif last: update_data\["full_name"\] \= last \# Only last name given  
                  else: update_data\["full_name"\] \= None \# Both cleared  
             \# If existing not found, update will fail later anyway

        try:  
            updated_profile \= await self.people_repo.update_profile(profile_id, update_data)  
            if not updated_profile:  
                 \# Repo returns None if not found  
                 raise ProfileNotFoundError(identifier=profile_id)  
            log.success("Profile updated successfully.")  
            return updated_profile  
        except ProfileNotFoundError as e:  
            log.warning(f"Profile not found for update: {e}")  
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))  
        except DuplicateKeyError as e:  
             \# Determine field and raise specific error  
             field \= "email" if "email" in str(e) else "whatsapp_id" if "whatsapp_id" in str(e) else "user_id" if "user_id" in str(e) else "identifier"  
             log.warning(f"Duplicate profile detected on update for {field}.")  
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Update failed: Another profile exists with this {field}.")  
        except RepositoryError as e:  
             log.exception("Repository error during profile update.")  
             raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Database error: {e}")  
        except Exception as e:  
            log.exception("Unexpected error during profile update.")  
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    \# Add methods for role management if needed  
    async def add_role_to_profile(self, profile_id: str, role: str) \-\> bool:  
         return await self.people_repo.add_role(profile_id, role)

    async def remove_role_from_profile(self, profile_id: str, role: str) \-\> bool:  
         return await self.people_repo.remove_role(profile_id, role)
