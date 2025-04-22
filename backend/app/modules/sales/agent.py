# app/modules/sales/agent.py  
from app.agents.base_agent import BaseAgent, AgentExecutionError  
from typing import Dict, Any, Optional, List, Type \# Import Type for schema mapping  
from pydantic import BaseModel, Field, ValidationError  
from fastapi import Depends \# Import Depends

# Import Sales specific components  
from .service import SalesService, CreateSaleInput, CreateSaleItemInput \# Import service and DTO  
from app.db.schemas.sale_schemas import SaleDoc, SaleStatus, SaleAgentType \# Import Sale models

# \--- Define Action-Specific Pydantic Payloads \---  
# These define the structure expected in the 'data' field of the MCPRequestPayload  
# They should contain only the data needed for the action, not context like agent_id

class CreateSaleActionPayload(BaseModel):  
    client_id: str \= Field(..., description="The profile ID of the client making the purchase.")  
    items: List\[CreateSaleItemInput\] \= Field(..., min_length=1, description="List of items (SKU and quantity).")  
    origin_channel: Optional\[str\] \= Field(None, description="Channel where the sale originated (e.g., 'whatsapp').")  
    contextual_note: Optional\[str\] \= Field(None, max_length=500, description="Optional note about the sale context.")  
    currency: Optional\[str\] \= Field(None, max_length=3, description="Currency code (defaults to system default).")

class GetSaleStatusActionPayload(BaseModel):  
    sale_id: str \= Field(..., description="The ID of the sale to check.")

class ListRecentSalesActionPayload(BaseModel):  
    \# No specific data needed, agent_id comes from context  
    limit: int \= Field(10, gt=0, le=50)

class SalesAgent(BaseAgent):  
    """Agent responsible for handling sales-related actions via MCP."""  
    agent_name \= "agentos_sales" \# Unique name for registration

    \# Map action names to internal methods and their expected payload schemas  
    action_schemas: Dict\[str, Optional\[Type\[BaseModel\]\]\] \= {  
        "create_sale": CreateSaleActionPayload,  
        "get_sale_status": GetSaleStatusActionPayload,  
        "list_recent_sales": ListRecentSalesActionPayload,  
        \# Add other actions: "cancel_sale", "get_product_details_for_sale", etc.  
    }

    \# Inject SalesService dependency using FastAPI's Depends mechanism if possible,  
    \# otherwise, rely on common_services dict passed during init.  
    \# This requires the AgentRegistry setup to handle FastAPI dependencies.  
    \# For simplicity now, assume we instantiate service inside using common_services.  
    def __init__(self, common_services: Optional\[Dict\[str, Any\]\] \= None):  
        super().__init__(common_services)  
        \# TODO: Implement proper Dependency Injection for services/repositories  
        \# This is a temporary placeholder for demonstration  
        try:  
            \# Attempt to get DB dependency from common services (passed by registry)  
            db \= self.common_services.get("db")  
            if not db: raise ValueError("Database instance ('db') not found in common_services for SalesAgent.")  
            \# Manually inject dependencies for now \- REPLACE WITH PROPER DI FRAMEWORK INTEGRATION  
            from app.modules.products.repository import ProductRepository \# Assumes exists  
            from app.modules.products.service import ProductService  
            from app.modules.people.repository import PeopleRepository \# Assumes exists  
            from app.modules.people.service import PeopleService  
            from app.modules.sales.repository import SaleRepository

            product_repo \= ProductRepository(db=db)  
            self.product_service \= ProductService(product_repo=product_repo)  
            people_repo \= PeopleRepository(db=db)  
            self.people_service \= PeopleService(people_repo=people_repo)  
            sale_repo \= SaleRepository(db=db)

            self.sales_service \= SalesService(  
                sale_repo=sale_repo,  
                product_service=self.product_service,  
                people_service=self.people_service,  
                db=db  
            )  
            self.logger.info("SalesService dependency initialized for SalesAgent.")  
        except Exception as e:  
             self.logger.exception("Failed to initialize dependencies for SalesAgent. Agent may not function correctly.")  
             \# Raise error or allow partial initialization? Raise for clarity.  
             raise RuntimeError(f"SalesAgent dependency initialization failed: {e}") from e

    async def execute(self, payload: Dict\[str, Any\], context: Optional\[Dict\[str, Any\]\] \= None) \-\> Dict\[str, Any\]:  
        """Executes a sales action based on the payload."""  
        action \= payload.get("action")  
        data \= payload.get("data", {})  
        \# Extract info from context (populated by MCP Gateway from JWT)  
        requesting_agent_id \= context.get("agent_id") if context else None  
        requesting_roles \= context.get("roles", \[\]) if context else \[\]  
        \# Determine agent type based on roles or context? Default to BOT for now.  
        agent_type \= SaleAgentType.HUMAN if "human_override" in requesting_roles else SaleAgentType.BOT

        log \= self.logger.bind(action=action, requesting_agent_id=requesting_agent_id)  
        log.info("Executing sales action.")

        if not requesting_agent_id:  
             raise AgentExecutionError(self.agent_name, "Agent ID missing from execution context.", status_code=401)

        \# \--- Action Routing & Validation \---  
        if not action or action not in self.action_schemas:  
            raise AgentExecutionError(self.agent_name, f"Unsupported action: {action}", status_code=400)

        PayloadSchema \= self.action_schemas\[action\]  
        validated_data: Optional\[BaseModel\] \= None  
        if PayloadSchema:  
            try:  
                validated_data \= PayloadSchema.model_validate(data) \# Pydantic v2  
            except ValidationError as e:  
                log.error(f"Payload validation failed: {e.errors()}")  
                raise AgentExecutionError(self.agent_name, f"Invalid payload for action '{action}'.", details=e.errors(), status_code=400)  
        else:  
             \# Action might not require specific data beyond context  
             pass

        \# \--- Call appropriate method \---  
        try:  
            if action \== "create_sale":  
                result_data \= await self._create_sale(validated_data, requesting_agent_id, agent_type, context)  
            elif action \== "get_sale_status":  
                result_data \= await self._get_sale_status(validated_data, requesting_agent_id, context)  
            elif action \== "list_recent_sales":  
                 result_data \= await self._list_recent_sales(validated_data, requesting_agent_id, context)  
            else:  
                \# Should be caught by initial check, but safeguard  
                raise AgentExecutionError(self.agent_name, f"Action '{action}' routing failed.", status_code=500)

            \# Return structured success result (Service methods should return Pydantic models or dicts)  
            \# The 'result' key holds the primary data returned by the action method  
            return result_data \# Service methods now return SaleDoc etc. which are dict-like

        except HTTPException as http_exc:  
             \# Catch HTTP exceptions raised by services (e.g., 404 Not Found, 409 Conflict)  
             log.warning(f"Action '{action}' failed with HTTP exception: {http_exc.status_code} \- {http_exc.detail}")  
             \# Re-raise as AgentExecutionError, preserving status code  
             raise AgentExecutionError(self.agent_name, http_exc.detail, status_code=http_exc.status_code)  
        except (ProductNotFoundError, ClientNotFoundError, InsufficientStockError, LowClientScoreError, DuplicateSaleError, SaleCreationError) as domain_exc:  
             log.warning(f"Action '{action}' failed with domain error: {domain_exc}")  
             \# Map domain errors to appropriate status codes for the MCP response  
             status_code \= 409 if isinstance(domain_exc, (InsufficientStockError, LowClientScoreError, DuplicateSaleError)) else \\  
                           404 if isinstance(domain_exc, (ProductNotFoundError, ClientNotFoundError)) else \\  
                           400 \# Default to 400 for other creation errors  
             raise AgentExecutionError(self.agent_name, str(domain_exc), status_code=status_code)  
        \# Let unexpected errors be caught by the registry's execute_agent_action handler

    \# \--- Action Implementations \---  
    async def _create_sale(self, data: CreateSaleActionPayload, agent_id: str, agent_type: SaleAgentType, context: Optional\[Dict\]) \-\> Dict:  
        """Calls the SalesService to create a sale."""  
        \# Map agent payload to service DTO  
        service_input \= CreateSaleInput(  
            client_id=data.client_id,  
            agent_id=agent_id,  
            agent_type=agent_type,  
            items=\[CreateSaleItemInput(sku=i\['sku'\], quantity=i\['quantity'\]) for i in data.items\], \# Re-validate items? Schema handles it.  
            origin_channel=data.origin_channel,  
            contextual_note=data.contextual_note,  
            currency=data.currency or settings.DEFAULT_CURRENCY,  
        )  
        created_sale \= await self.sales_service.create_sale(service_input)  
        \# Return the created sale document as a dictionary  
        return created_sale.model_dump(mode='json', by_alias=True)

    async def _get_sale_status(self, data: GetSaleStatusPayload, agent_id: str, context: Optional\[Dict\]) \-\> Dict:  
        """Calls SalesService to get sale status."""  
        sale \= await self.sales_service.get_sale_by_id(data.sale_id)  
        \# TODO: Add authorization check \- can this agent_id view this sale_id?  
        return {"sale_id": data.sale_id, "status": sale.status.value}

    async def _list_recent_sales(self, data: ListRecentSalesActionPayload, agent_id: str, context: Optional\[Dict\]) \-\> Dict:  
         """Calls SalesService to list recent sales for the agent."""  
         sales_list \= await self.sales_service.list_recent_sales_for_user(agent_id, limit=data.limit)  
         \# Return list of SaleDoc dictionaries  
         return {"sales": \[s.model_dump(mode='json', by_alias=True) for s in sales_list\]}
