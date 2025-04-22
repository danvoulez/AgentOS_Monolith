# app/modules/delivery/agent.py
# Agent interface for delivery-related actions via MCP

from app.agents.base_agent import BaseAgent, AgentExecutionError
from typing import Dict, Any, Optional, List, Type
from pydantic import BaseModel, Field, ValidationError
from fastapi import Depends
from datetime import datetime, timezone

# Import Delivery specific components
from .service import DeliveryService
from app.db.schemas.delivery_schemas import DeliverySessionDoc, DeliveryStatus, LocationPoint, TrackingEventDoc

# --- Action Payloads ---
class GetDeliveryStatusPayload(BaseModel):
    delivery_id: str

class UpdateCourierLocationPayload(BaseModel):
    delivery_id: str
    location: LocationPoint
    timestamp: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))

class UpdateDeliveryStatusPayload(BaseModel):
    delivery_id: str
    status: DeliveryStatus
    description: Optional[str] = None
    location: Optional[LocationPoint] = None

class DeliveryAgent(BaseAgent):
    """Agent for handling delivery actions."""
    agent_name = "agentos_delivery"

    action_schemas: Dict[str, Optional[Type[BaseModel]]] = {
        "get_status": GetDeliveryStatusPayload,
        "update_location": UpdateCourierLocationPayload,
        "update_status": UpdateDeliveryStatusPayload,
    }

    def __init__(self, common_services: Optional[Dict[str, Any]] = None):
        super().__init__(common_services)
        try:
            db = self.common_services.get("db")
            if not db:
                raise ValueError("DB not in common_services for DeliveryAgent")
            from .repository import DeliveryRepository
            from app.modules.people.repository import PeopleRepository
            from app.modules.people.service import PeopleService

            delivery_repo = DeliveryRepository(db=db)
            people_repo = PeopleRepository(db=db)
            people_service = PeopleService(people_repo=people_repo)

            self.delivery_service = DeliveryService(
                delivery_repo=delivery_repo,
                people_service=people_service
            )
            self.logger.info("DeliveryService dependency initialized for DeliveryAgent.")
        except Exception as e:
            self.logger.exception("Failed to initialize dependencies for DeliveryAgent.")
            raise RuntimeError(f"DeliveryAgent DI failed: {e}") from e

    async def execute(self, payload: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        action = payload.get("action")
        data = payload.get("data", {})
        actor_id = context.get("agent_id") if context else "unknown_actor"
        actor_roles = context.get("roles", []) if context else []

        log = self.logger.bind(action=action, actor_id=actor_id)
        log.info("Executing delivery action.")

        if not action or action not in self.action_schemas:
            raise AgentExecutionError(self.agent_name, f"Unsupported action: {action}", status_code=400)

        PayloadSchema = self.action_schemas[action]
        validated_data: Optional[BaseModel] = None
        if PayloadSchema:
            try:
                validated_data = PayloadSchema.model_validate(data)
            except ValidationError as e:
                raise AgentExecutionError(self.agent_name, f"Invalid payload for '{action}'.", details=e.errors(), status_code=400)

        if action == "update_location" and "courier" not in actor_roles:
            raise AgentExecutionError(self.agent_name, "Only couriers can update location.", status_code=403)
        if action == "update_status" and validated_data.status in [DeliveryStatus.DELIVERED, DeliveryStatus.FAILED_ATTEMPT] and "courier" not in actor_roles:
            raise AgentExecutionError(self.agent_name, f"Only couriers can set status to {validated_data.status.value}.", status_code=403)

        try:
            result_data = None
            if action == "get_status":
                delivery = await self.delivery_service.get_delivery_by_id(validated_data.delivery_id)
                result_data = {"delivery_id": delivery.id, "status": delivery.current_status.value, "updated_at": delivery.updated_at}
            elif action == "update_location":
                updated_delivery = await self.delivery_service.update_courier_location(
                    validated_data.delivery_id, actor_id, validated_data.location, validated_data.timestamp
                )
                result_data = {"delivery_id": updated_delivery.id, "status": updated_delivery.current_status.value}
            elif action == "update_status":
                updated_delivery = await self.delivery_service.update_delivery_status(
                    validated_data.delivery_id, validated_data.status, actor_id,
                    validated_data.description, validated_data.location
                )
                result_data = {"delivery_id": updated_delivery.id, "new_status": updated_delivery.current_status.value}
            else:
                raise AgentExecutionError(self.agent_name, f"Action '{action}' handler not implemented.", status_code=501)

            return result_data

        except (DeliveryNotFoundError, InvalidDeliveryStatusError) as domain_exc:
            log.warning(f"Action '{action}' failed with domain error: {domain_exc}")
            status_code = 404 if isinstance(domain_exc, DeliveryNotFoundError) else 409
            raise AgentExecutionError(self.agent_name, str(domain_exc), status_code=status_code)
        except HTTPException as http_exc:
            log.warning(f"Action '{action}' failed with HTTP exception: {http_exc.status_code} - {http_exc.detail}")
            raise AgentExecutionError(self.agent_name, http_exc.detail, status_code=http_exc.status_code)
        except Exception as e:
            log.exception(f"Unexpected error executing action '{action}'.")
            raise AgentExecutionError(self.agent_name, f"Internal error during action '{action}'.", details=str(e), status_code=500)
