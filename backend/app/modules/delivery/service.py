# app/modules/delivery/service.py
from typing import Optional, List, Dict, Any
from fastapi import Depends, HTTPException, status
from app.db.schemas.delivery_schemas import DeliverySessionDoc, DeliveryStatus, TrackingEventDoc, LocationPoint, DeliveryItem
from app.modules.delivery.repository import DeliveryRepository
# Import other needed services/clients for integrations
# from app.integrations.delivery_client import delivery_platform_client # Example
from app.modules.people.service import PeopleService # To validate client/courier IDs
# Import notification service for PubSub events
from app.services.notification_service import notification_service
from app.services.audit_service import audit_service
from app.core.config import settings
from app.core.logging_setup import logger
from app.modules.delivery.exceptions import * # Import delivery exceptions
from app.core.exceptions import RepositoryError, IntegrationError, ClientNotFoundError, ProfileNotFoundError
from datetime import datetime, timezone
import uuid # For generating IDs if needed

class DeliveryService:
    """Service layer for delivery business logic."""
    def __init__(
        self,
        delivery_repo: DeliveryRepository = Depends(),
        people_service: PeopleService = Depends(),
        # Inject celery app instance if needed to dispatch tasks
        # celery_app = Depends(get_celery_app) # Requires a dependency provider
    ):
        self.delivery_repo = delivery_repo
        self.people_service = people_service
        # self.celery_app = celery_app
        logger.debug("DeliveryService initialized.")

    async def create_delivery(self, sale_id: str, client_id: str, items: List[Dict], pickup_addr: str, delivery_addr: str) -> DeliverySessionDoc:
        """Creates a new delivery session, typically triggered by a sale."""
        log = logger.bind(sale_id=sale_id, client_id=client_id)
        log.info("Creating new delivery session.")

        # 1. Validate Client ID existence (optional, but good practice)
        try:
            client_profile = await self.people_service.get_profile_by_id(client_id)
            if not client_profile or not client_profile.is_active:
                raise ClientNotFoundError(client_id=client_id)
        except ProfileNotFoundError as e:
             log.warning(f"Client profile not found for delivery creation: {e}")
             raise e # Re-raise to be caught by endpoint/agent

        # 2. Prepare Delivery Item list (map from sale items if needed)
        delivery_items = [DeliveryItem(**item) for item in items] # Assumes items dict matches DeliveryItem

        # 3. Create DeliverySessionDoc data
        delivery_data = {
            "sale_id": sale_id,
            "client_profile_id": client_id,
            "items": [item.model_dump() for item in delivery_items],
            "pickup_address": pickup_addr,
            "delivery_address": delivery_addr,
            # Status defaults to PENDING_ASSIGNMENT in repository create
        }

        # 4. Save to Repository
        try:
            delivery_doc = await self.delivery_repo.create_delivery(delivery_data)
            if not delivery_doc:
                raise DeliveryError("Failed to create delivery document in repository.")

            log.success(f"Delivery session created: {delivery_doc.id}")

            # 5. Trigger Courier Assignment Task (async)
            # Use Celery for reliability if configured
            if settings.CELERY_ENABLED:
                 try:
                     # from app.worker.tasks import assign_courier_task # Import task
                     # assign_courier_task.delay(str(delivery_doc.id))
                     log.info("Dispatched assign_courier_task to Celery.")
                 except Exception as task_e:
                      log.exception("Failed to dispatch assign_courier task.")
                      # Log error but don't fail the delivery creation itself? Or mark delivery as ERROR? Mark as ERROR.
                      # await self.update_delivery_status(str(delivery_doc.id), DeliveryStatus.ERROR, "system", f"Failed dispatch: {task_e}")
            else:
                 log.warning("Celery not enabled, courier assignment must be triggered manually or via another mechanism.")

            # 6. Audit Log
            await audit_service.log_event(
                actor_id="sales_service", action="create_delivery", entity_type="delivery",
                entity_id=str(delivery_doc.id), success=True, details={"sale_id": sale_id}
            )

            return delivery_doc

        except RepositoryError as e:
            log.exception("Repository error during delivery creation.")
            raise DeliveryError(f"Database error creating delivery: {e}") from e
        except Exception as e:
            log.exception("Unexpected error during delivery creation.")
            raise DeliveryError(f"Unexpected error creating delivery: {e}") from e

    async def update_delivery_status(
        self, delivery_id: str, new_status: DeliveryStatus, actor_id: str,
        description: Optional[str] = None, location: Optional[LocationPoint] = None
    ) -> DeliverySessionDoc:
        """Updates the delivery status and adds a tracking event."""
        log = logger.bind(delivery_id=delivery_id, new_status=new_status.value, actor_id=actor_id)
        log.info("Updating delivery status.")

        # 1. Get current delivery state (needed for validation/context)
        delivery = await self.delivery_repo.get_delivery_by_id(delivery_id)
        if not delivery:
            raise DeliveryNotFoundError(delivery_id)

        # 2. Validate status transition (implement state machine logic if needed)
        # Example: Cannot go from DELIVERED back to IN_TRANSIT
        # if not self._is_valid_transition(delivery.current_status, new_status):
        #     raise InvalidDeliveryStatusError(delivery_id, delivery.current_status.value, f"set status to {new_status.value}")

        # 3. Create Tracking Event
        event_desc = description or f"Status updated to {new_status.name}"
        event = TrackingEventDoc(
            status=new_status,
            description=event_desc,
            actor_id=actor_id,
            location=location
        )

        # 4. Update Repository (adds event and sets status atomically)
        try:
            updated_delivery = await self.delivery_repo.add_tracking_event(
                delivery_id, event, new_status, location.model_dump() if location else None
            )
            if not updated_delivery:
                # Should not happen if get_by_id succeeded, but handle defensively
                raise DeliveryError("Failed to update delivery status after initial fetch.")

            log.success("Delivery status updated successfully.")

            # 5. Publish Event to Redis Pub/Sub
            await notification_service.publish_websocket_update(
                target="user", # Notify client and maybe courier? Or use separate events?
                target_id=updated_delivery.client_profile_id, # Target the client
                event_type="delivery_status_changed",
                data={
                    "delivery_id": str(updated_delivery.id),
                    "new_status": new_status.value,
                    "description": event_desc,
                    "timestamp": event.timestamp.isoformat(),
                    "location": location.model_dump() if location else None,
                }
            )
            # TODO: Maybe publish a separate event for the courier if needed

            # 6. Audit Log
            await audit_service.log_event(
                actor_id=actor_id, action=f"update_delivery_status_{new_status.value}", entity_type="delivery",
                entity_id=delivery_id, success=True, details={"description": event_desc}
            )

            return updated_delivery

        except RepositoryError as e:
            log.exception("Repository error during status update.")
            raise DeliveryError(f"Database error updating delivery status: {e}") from e
        except Exception as e:
            log.exception("Unexpected error during status update.")
            raise DeliveryError(f"Unexpected error updating delivery status: {e}") from e

    async def update_courier_location(
        self, delivery_id: str, courier_id: str, location_data: LocationPoint, timestamp: datetime
        ) -> DeliverySessionDoc:
         """Updates the courier's location for a specific delivery."""
         log = logger.bind(delivery_id=delivery_id, courier_id=courier_id)
         log.debug(f"Updating courier location: {location_data.coordinates}")

         # 1. Get delivery to validate courier and status
         delivery = await self.delivery_repo.get_delivery_by_id(delivery_id)
         if not delivery: raise DeliveryNotFoundError(delivery_id)
         if delivery.courier_profile_id != courier_id:
              raise HTTPException(status.HTTP_403_FORBIDDEN, "Courier not assigned to this delivery.")
         if delivery.current_status not in [DeliveryStatus.PICKING_UP, DeliveryStatus.IN_TRANSIT, DeliveryStatus.NEAR_DESTINATION, DeliveryStatus.FAILED_ATTEMPT]:
              raise InvalidDeliveryStatusError(delivery_id, delivery.current_status.value, "update location")

         # 2. Update location in DB
         try:
             updated_delivery = await self.delivery_repo.update_delivery(
                 delivery_id,
                 {"current_location": location_data.model_dump(), "updated_at": timestamp}
             )
             if not updated_delivery: raise DeliveryError("Failed to update location after fetching.")

             # 3. Publish location update event
             await notification_service.publish_websocket_update(
                 target="user", # Notify client
                 target_id=delivery.client_profile_id,
                 event_type="delivery_location_update",
                 data={
                     "delivery_id": delivery_id,
                     "location": location_data.model_dump(),
                     "timestamp": timestamp.isoformat()
                 }
             )
             # Also publish to a courier-specific channel if needed
             # await notification_service.publish_websocket_update(target="courier", target_id=courier_id, ...)

             return updated_delivery
         except RepositoryError as e:
              log.exception("Repository error updating location.")
              raise DeliveryError(f"Database error updating location: {e}") from e
         except Exception as e:
              log.exception("Unexpected error updating location.")
              raise DeliveryError(f"Unexpected error updating location: {e}") from e

    # TODO: Add methods for chat handling, triggering fallback task, etc.
    # async def add_chat_message(...)
    # async def get_chat_history(...)
    # async def trigger_fallback(...) -> Uses delivery_repo to get context and celery task sender
