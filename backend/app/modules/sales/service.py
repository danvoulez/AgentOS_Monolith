# app/modules/sales/service.py  
from typing import Optional, List, Dict, Any  
from fastapi import Depends, HTTPException, status \# Use FastAPI Depends for DI  
from datetime import datetime, timedelta, timezone  
import asyncio

# Import Schemas, Models, Repositories, Services, Exceptions for this module  
from app.db.schemas.sale_schemas import SaleDoc, SaleItem, SaleStatus, SaleAgentType  
from app.db.schemas.product_schemas import ProductDoc \# Assuming product schemas exist  
from app.db.schemas.people_schemas import ProfileDoc \# Assuming people schemas exist  
from app.modules.sales.repository import SaleRepository  
# Assume product service exists and is injectable  
from app.modules.products.service import ProductService \# Adjust path if needed  
# Assume people service exists and is injectable  
from app.modules.people.service import PeopleService \# Adjust path if needed  
from app.modules.sales.exceptions import \* \# Import all sales exceptions  
from app.core.exceptions import RepositoryError, IntegrationError \# Import core exceptions  
from app.core.config import settings \# Import settings  
from app.core.logging_setup import logger \# Use configured logger  
from app.services.notification_service import notification_service \# For publishing events  
from app.services.audit_service import audit_service \# For logging audits

# Pydantic model for the create_sale input data within the service  
class CreateSaleItemInput(BaseModel):  
    sku: str  
    quantity: int \= Field(..., gt=0)

class CreateSaleInput(BaseModel):  
    client_id: str  
    agent_id: str \# This will be the authenticated user/agent ID  
    agent_type: SaleAgentType  
    items: List\[CreateSaleItemInput\] \= Field(..., min_length=1)  
    origin_channel: Optional\[str\] \= None  
    contextual_note: Optional\[str\] \= None  
    currency: str \= Field(default=settings.DEFAULT_CURRENCY)  
    \# idempotency_key: Optional\[str\] \= None \# Consider adding for robust retries

class SalesService:  
    """Service layer for sales business logic."""  
    def __init__(  
        self,  
        \# Inject dependencies using FastAPI's Depends  
        sale_repo: SaleRepository \= Depends(),  
        product_service: ProductService \= Depends(),  
        people_service: PeopleService \= Depends(),  
        \# Add other dependencies like PricingService, CommissionService when implemented  
        \# pricing_service: PricingService \= Depends(),  
        \# integration_service: IntegrationService \= Depends(), \# For Banking/Delivery clients  
        db: AsyncIOMotorDatabase \= Depends(get_database) \# For transactions  
    ):  
        self.sale_repo \= sale_repo  
        self.product_service \= product_service  
        self.people_service \= people_service  
        \# self.pricing_service \= pricing_service  
        \# self.integration_service \= integration_service  
        self.db_client \= db.client \# Get client from DB object for transactions  
        logger.debug("SalesService initialized with dependencies.")

    async def create_sale(self, sale_input: CreateSaleInput) \-\> SaleDoc:  
        """  
        Orchestrates the creation of a new sale.  
        1\. Validates client and duplicate potential.  
        2\. Starts DB transaction.  
        3\. Allocates stock for each item.  
        4\. Calculates price and totals (basic for now).  
        5\. Creates SaleDoc in DB.  
        6\. Commits transaction.  
        7\. Schedules async post-sale actions (audit, notifications, integrations).  
        """  
        log \= logger.bind(client_id=sale_input.client_id, agent_id=sale_input.agent_id)  
        log.info(f"SalesService attempting to create sale with {len(sale_input.items)} items.")

        \# \--- 1\. Pre-checks (Outside Transaction) \---  
        \# Fetch client profile  
        client_profile \= await self.people_service.get_profile_by_id(sale_input.client_id)  
        if not client_profile or not client_profile.is_active:  
            log.warning("Client not found or inactive.")  
            raise ClientNotFoundError(client_id=sale_input.client_id)

        \# TODO: Check client score if implemented in PeopleService/ProfileDoc  
        \# min_score \= settings.MIN_CLIENT_SCORE  
        \# client_score \= client_profile.metadata.get("sales_score", 0\) \# Example field  
        \# if client_score \< min_score:  
        \#     log.warning(f"Client score {client_score} below minimum {min_score}.")  
        \#     raise LowClientScoreError(client_id=sale_input.client_id, score=client_score, min_score=min_score)

        \# Check for potential duplicate sale  
        await self._check_duplicate_sale(sale_input.agent_id, sale_input.client_id, sale_input.items)

        \# \--- 2\. DB Transaction \---  
        \# Use context manager for session handling with Motor \>= 2.5  
        async with await self.db_client.start_session() as session:  
            async with session.with_transaction():  
                log.info("Starting sale creation transaction.")  
                processed_items: List\[SaleItem\] \= \[\]  
                total_amount \= 0.0  
                allocated_products: List\[ProductDoc\] \= \[\] \# Keep track for potential rollback

                try:  
                    \# \--- 3\. Fetch products and allocate stock \---  
                    for item_in in sale_input.items:  
                        log.debug(f"Processing item: SKU={item_in.sku}, Qty={item_in.quantity}")  
                        \# Allocate stock using ProductService (handles optimistic locking, raises exceptions)  
                        \# This implicitly fetches the active product as well  
                        updated_product \= await self.product_service.allocate_stock(item_in.sku, item_in.quantity)  
                        allocated_products.append(updated_product) \# Track successfully allocated

                        \# \--- 4\. Calculate Price \---  
                        \# TODO: Integrate PricingService based on product and client_profile.category  
                        \# unit_price \= await self.pricing_service.calculate_client_price(updated_product, client_profile.category)  
                        unit_price \= updated_product.standard_selling_price \# Placeholder

                        total_item_price \= round(unit_price \* item_in.quantity, 2\)  
                        total_amount \+= total_item_price

                        processed_items.append(SaleItem(  
                            product_id=str(updated_product.id),  
                            sku=updated_product.sku,  
                            name=updated_product.name,  
                            quantity=item_in.quantity,  
                            unit_price=unit_price,  
                            total_price=total_item_price  
                        ))  
                        log.debug(f"Item {item_in.sku} processed. Price: {unit_price}, Total Item: {total_item_price}")

                    \# \--- 5\. Create Sale Document \---  
                    now \= datetime.now(timezone.utc)  
                    sale_doc_data \= {  
                        "client_id": sale_input.client_id,  
                        "agent_id": sale_input.agent_id,  
                        "agent_type": sale_input.agent_type,  
                        "items": \[item.model_dump() for item in processed_items\],  
                        "total_amount": round(total_amount, 2),  
                        "currency": sale_input.currency,  
                        "status": SaleStatus.PROCESSING, \# Initial status  
                        "status_history": \[{"status": SaleStatus.PROCESSING.value, "timestamp": now.isoformat(), "actor_id": sale_input.agent_id}\],  
                        "origin_channel": sale_input.origin_channel,  
                        "contextual_note": sale_input.contextual_note,  
                        "created_at": now, "updated_at": now,  
                        "banking_sync_status": "pending", "delivery_status": "pending",  
                        \# TODO: Calculate commission, margin  
                    }  
                    created_sale \= await self.sale_repo.create_sale(sale_doc_data) \# Use repo method  
                    if not created_sale:  
                        raise SaleCreationError("Failed to save sale document in repository after processing items.")

                    log.success(f"Sale transaction completed. Sale ID: {created_sale.id}")  
                    \# \--- Transaction Commits Here \---

                except (ProductNotFoundError, InsufficientStockError, LowClientScoreError, DuplicateSaleError, ClientNotFoundError) as domain_exc:  
                     \# If known domain errors occur during item processing, abort transaction  
                     log.warning(f"Aborting sale transaction due to domain error: {domain_exc}")  
                     \# Transaction automatically rolls back on exception exit  
                     raise domain_exc \# Re-raise specific error  
                except Exception as e:  
                     log.exception("Unexpected error during sale creation transaction.")  
                     \# Transaction automatically rolls back  
                     \# Raise a generic creation error  
                     raise SaleCreationError(f"Unexpected error during transaction: {e}") from e

        \# \--- 6\. Post-Transaction Actions \---  
        if created_sale:  
            log.info(f"Scheduling post-sale actions for Sale ID: {created_sale.id}")  
            \# Use asyncio.create_task for fire-and-forget, or Celery for reliability  
            asyncio.create_task(self._trigger_post_sale_actions(str(created_sale.id), sale_input.agent_id))  
        else:  
             \# Should only happen if transaction failed silently (unlikely with Motor)  
             log.error("Sale creation transaction seemed to succeed but no sale object returned.")  
             \# Raise error to indicate failure to caller  
             raise SaleCreationError("Sale creation failed unexpectedly post-transaction.")

        return created_sale

    async def _check_duplicate_sale(self, agent_id: str, client_id: str, items: List\[CreateSaleItemInput\]):  
        """Checks repo for potential duplicate sales."""  
        time_window \= timedelta(minutes=settings.DUPLICATE_SALE_WINDOW_MINUTES)  
        try:  
            recent_sales \= await self.sale_repo.find_recent_by_agent_and_client(agent_id, client_id, time_window)  
            if not recent_sales: return \# No recent sales, no duplicate

            new_items_sig \= "|".join(sorted(\[f"{i.sku}:{i.quantity}" for i in items\]))

            for sale in recent_sales:  
                sale_items_sig \= "|".join(sorted(\[f"{item.sku}:{item.quantity}" for item in sale.items\]))  
                if sale_items_sig \== new_items_sig:  
                    logger.warning(f"Duplicate sale detected for client {client_id} / agent {agent_id}. Previous sale: {sale.id}")  
                    raise DuplicateSaleError(client_id=client_id, agent_id=agent_id)  
        except RepositoryError:  
            logger.exception("Failed to check for duplicate sales, proceeding cautiously.")  
            \# Decide: Proceed or fail safe? Proceed for now.

    async def _trigger_post_sale_actions(self, sale_id: str, actor_id: str):  
        """Triggers async actions after sale confirmation."""  
        log \= logger.bind(sale_id=sale_id, service="PostSaleActions")  
        log.info("Initiating post-sale actions.")

        \# 1\. Audit Log  
        await audit_service.log_event(  
            actor_id=actor_id, action="create_sale", entity_type="sale", entity_id=sale_id, success=True,  
            \# details={"total": ..., "item_count": ...} \# Add details later from fetched sale?  
        )

        \# 2\. Publish Event for Real-time Updates / Other Listeners  
        await notification_service.publish_websocket_update(  
            target="all", \# Or maybe target specific users/groups?  
            target_id="sales_dashboard", \# Example group  
            event_type="sale_created",  
            data={"sale_id": sale_id, "status": SaleStatus.PROCESSING.value} \# Send minimal data  
        )

        \# 3\. Trigger Integrations (Banking, Delivery) via Celery for reliability  
        if settings.CELERY_ENABLED:  
             log.info("Dispatching integration tasks to Celery.")  
             \# from app.worker.tasks import process_banking_sync, initiate_delivery_sync \# Import tasks  
             \# process_banking_sync.delay(sale_id)  
             \# initiate_delivery_sync.delay(sale_id)  
        else:  
             \# Fallback: Run directly with asyncio.create_task (less reliable)  
             log.warning("Celery not enabled, running integrations directly (less reliable).")  
             \# TODO: Implement direct calls to IntegrationService here if needed  
             \# await asyncio.gather(  
             \#      self.integration_service.sync_banking(sale_id),  
             \#      self.integration_service.initiate_delivery(sale_id),  
             \#      return_exceptions=True \# Handle potential errors  
             \# )  
             pass \# Placeholder

        log.info("Post-sale action triggers finished.")

    async def get_sale_by_id(self, sale_id: str) \-\> SaleDoc:  
        """Gets sale details by ID."""  
        log \= logger.bind(sale_id=sale_id)  
        log.info("Getting sale by ID.")  
        sale \= await self.sale_repo.get_sale_by_id(sale_id)  
        if not sale:  
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found.")  
        return sale

    async def list_recent_sales_for_user(self, user_id: str, limit: int \= 20\) \-\> List\[SaleDoc\]:  
         """Lists recent sales where the user is either the client or the agent."""  
         log \= logger.bind(user_id=user_id, limit=limit)  
         log.info("Listing recent sales for user.")  
         \# This requires querying based on client_id OR agent_id  
         \# TODO: Implement this query logic in SaleRepository  
         \# query \= {"$or": \[{"client_id": user_id}, {"agent_id": user_id}\]}  
         \# return await self.sale_repo.list_sales(query=query, limit=limit, sort=\[("created_at", \-1)\])  
         return await self.sale_repo.list_sales(client_id=user_id, limit=limit) \# Simplified for now
