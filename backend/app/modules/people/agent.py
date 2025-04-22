# app/modules/people/agent.py  
from app.agents.base_agent import BaseAgent, AgentExecutionError  
from typing import Dict, Any, Optional, List, Type  
from pydantic import BaseModel, Field, ValidationError, EmailStr  
from fastapi import Depends \# For injecting service

# Import People specific components  
from .service import PeopleService  
from app.db.schemas.people_schemas import ProfileDoc, ProfileCreate, ProfileUpdate, ProfileType \# Import schemas

# \--- Action Payloads \---  
class CreateProfilePayload(ProfileCreate): \# Reuse existing schema  
    pass

class GetProfilePayload(BaseModel):  
    identifier: str \= Field(..., description="Identifier (profile_id, user_id, email, whatsapp_id)")  
    id_type: str \= Field("email", examples=\["profile_id", "user_id", "email", "whatsapp_id"\], description="Type of identifier provided")

class UpdateProfilePayload(BaseModel):  
    profile_id: str \# ID required to know which profile to update  
    update_data: ProfileUpdate \# The actual update fields

class AddRolePayload(BaseModel):  
     profile_id: str  
     role: str

class RemoveRolePayload(BaseModel):  
     profile_id: str  
     role: str

class PeopleAgent(BaseAgent):  
    """Agent for managing user/entity profiles."""  
    agent_name \= "agentos_people"

    action_schemas: Dict\[str, Optional\[Type\[BaseModel\]\]\] \= {  
        "create_profile": CreateProfilePayload,  
        "get_profile": GetProfilePayload,  
        "update_profile": UpdateProfilePayload,  
        "add_role": AddRolePayload,  
        "remove_role": RemoveRolePayload,  
    }

    def __init__(self, common_services: Optional\[Dict\[str, Any\]\] \= None):  
        super().__init__(common_services)  
        \# TODO: Implement proper DI  
        try:  
            db \= self.common_services.get("db")  
            if not db: raise ValueError("DB not in common_services")  
            from .repository import PeopleRepository \# Import repo  
            people_repo \= PeopleRepository(db=db)  
            self.people_service \= PeopleService(people_repo=people_repo)  
            self.logger.info("PeopleService dependency initialized for PeopleAgent.")  
        except Exception as e:  
            self.logger.exception("Failed to initialize dependencies for PeopleAgent.")  
            raise RuntimeError(f"PeopleAgent DI failed: {e}") from e

    async def execute(self, payload: Dict\[str, Any\], context: Optional\[Dict\[str, Any\]\] \= None) \-\> Dict\[str, Any\]:  
        action \= payload.get("action")  
        data \= payload.get("data", {})  
        requesting_agent_id \= context.get("agent_id") if context else "unknown_agent"

        log \= self.logger.bind(action=action, requesting_agent_id=requesting_agent_id)  
        log.info("Executing people action.")

        if not action or action not in self.action_schemas:  
            raise AgentExecutionError(self.agent_name, f"Unsupported action: {action}", status_code=400)

        PayloadSchema \= self.action_schemas\[action\]  
        validated_data: Optional\[BaseModel\] \= None  
        if PayloadSchema:  
            try: validated_data \= PayloadSchema.model_validate(data)  
            except ValidationError as e: raise AgentExecutionError(self.agent_name, f"Invalid payload for '{action}'.", details=e.errors(), status_code=400)

        try:  
            if action \== "create_profile":  
                 result_data \= await self._create_profile(validated_data)  
            elif action \== "get_profile":  
                 result_data \= await self._get_profile(validated_data)  
            elif action \== "update_profile":  
                 result_data \= await self._update_profile(validated_data)  
            elif action \== "add_role":  
                 result_data \= await self._add_role(validated_data)  
            elif action \== "remove_role":  
                 result_data \= await self._remove_role(validated_data)  
            else: raise AgentExecutionError(self.agent_name, f"Action '{action}' routing failed.", status_code=500)

            \# Return success structure  
            return result_data \# Service methods return Pydantic models or bool

        except HTTPException as http_exc:  
            \# Catch errors raised by the service (e.g., 404, 400\)  
            log.warning(f"Action '{action}' failed with HTTP exception: {http_exc.status_code} \- {http_exc.detail}")  
            raise AgentExecutionError(self.agent_name, http_exc.detail, status_code=http_exc.status_code)  
        except Exception as e:  
             log.exception(f"Unexpected error executing action '{action}'.")  
             raise AgentExecutionError(self.agent_name, f"Internal error during action '{action}'.", details=str(e), status_code=500)

    \# \--- Action Implementations \---  
    async def _create_profile(self, data: CreateProfilePayload) \-\> Dict:  
         profile_doc \= await self.people_service.create_profile(data)  
         return profile_doc.model_dump(mode='json', by_alias=True)

    async def _get_profile(self, data: GetProfilePayload) \-\> Dict:  
         profile \= None  
         if data.id_type \== "profile_id":  
             profile \= await self.people_service.get_profile_by_id(data.identifier)  
         else:  
             profile \= await self.people_service.find_profile(\*\*{data.id_type: data.identifier})

         if not profile:  
             raise AgentExecutionError(self.agent_name, "Profile not found.", status_code=404)  
         return profile.model_dump(mode='json', by_alias=True)

    async def _update_profile(self, data: UpdateProfilePayload) \-\> Dict:  
         updated_profile \= await self.people_service.update_profile(data.profile_id, data.update_data)  
         return updated_profile.model_dump(mode='json', by_alias=True)

    async def _add_role(self, data: AddRolePayload) \-\> Dict:  
        success \= await self.people_service.add_role_to_profile(data.profile_id, data.role)  
        if not success: raise AgentExecutionError(self.agent_name, "Failed to add role (profile not found?).", status_code=404)  
        return {"success": True, "profile_id": data.profile_id, "role_added": data.role}

    async def _remove_role(self, data: RemoveRolePayload) \-\> Dict:  
        success \= await self.people_service.remove_role_from_profile(data.profile_id, data.role)  
        if not success: raise AgentExecutionError(self.agent_name, "Failed to remove role (profile not found?).", status_code=404)  
        return {"success": True, "profile_id": data.profile_id, "role_removed": data.role}
