# app/modules/sales/agent.py
from app.agents.base_agent import BaseAgent, AgentExecutionError
from typing import Dict, Any, Optional, List, Type
from pydantic import BaseModel, Field, ValidationError
from fastapi import Depends

# Import Sales specific components
from .service import SalesService, CreateSaleInput, CreateSaleItemInput
from app.db.schemas.sale_schemas import SaleDoc, SaleStatus, SaleAgentType

# Define Action-Specific Pydantic Payloads
class CreateSaleActionPayload(BaseModel):
    client_id: str = Field(..., description="The profile ID of the client making the purchase.")
    items: List[CreateSaleItemInput] = Field(..., min_length=1, description="List of items (SKU and quantity).")
    origin_channel: Optional[str] = Field(None, description="Channel where the sale originated (e.g., 'whatsapp').")
    contextual_note: Optional[str] = Field(None, max_length=500, description="Optional note about the sale context.")
    currency: Optional[str] = Field(None, max_length=3, description="Currency code (defaults to system default).")

class GetSaleStatusActionPayload(BaseModel):
    sale_id: str = Field(..., description="The ID of the sale to check.")

class ListRecentSalesActionPayload(BaseModel):
    limit: int = Field(10, gt=0, le=50)

class SalesAgent(BaseAgent):
    """Agent responsible for handling sales-related actions via MCP."""
    agent_name = "agentos_sales"

    action_schemas: Dict[str, Optional[Type[BaseModel]]] = {
        "create_sale": CreateSaleActionPayload,
        "get_sale_status": GetSaleStatusActionPayload,
        "list_recent_sales": ListRecentSalesActionPayload,
    }

    def __init__(self, common_services: Optional[Dict[str, Any]] = None):
        super().__init__(common_services)
        try:
            db = self.common_services.get("db")
            if not db: raise ValueError("Database instance ('db') not found in common_services for SalesAgent.")
            from app.modules.products.repository import ProductRepository
            from app.modules.products.service import ProductService
            from app.modules.people.repository import PeopleRepository
            from app.modules.people.service import PeopleService
            from app.modules.sales.repository import SaleRepository

            product_repo = ProductRepository(db=db)
            self.product_service = ProductService(product_repo=product_repo)
            people_repo = PeopleRepository(db=db)
            self.people_service = PeopleService(people_repo=people_repo)
            sale_repo = SaleRepository(db=db)

            self.sales_service = SalesService(
                sale_repo=sale_repo,
                product_service=self.product_service,
                people_service=self.people_service,
                db=db
            )
            self.logger.info("SalesService dependency initialized for SalesAgent.")
        except Exception as e:
            self.logger.exception("Failed to initialize dependencies for SalesAgent. Agent may not function correctly.")
            raise RuntimeError(f"SalesAgent dependency initialization failed: {e}") from e

    async def execute(self, payload: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        action = payload.get("action")
        data = payload.get("data", {})
        requesting_agent_id = context.get("agent_id") if context else None
        requesting_roles = context.get("roles", []) if context else []
        agent_type = SaleAgentType.HUMAN if "human_override" in requesting_roles else SaleAgentType.BOT

        log = self.logger.bind(action=action, requesting_agent_id=requesting_agent_id)
        log.info("Executing sales action.")

        if not requesting_agent_id:
            raise AgentExecutionError(self.agent_name, "Agent ID missing from execution context.", status_code=401)

        if not action or action not in self.action_schemas:
            raise AgentExecutionError(self.agent_name, f"Unsupported action: {action}", status_code=400)

        PayloadSchema = self.action_schemas[action]
        validated_data: Optional[BaseModel] = None
        if PayloadSchema:
            try:
                validated_data = PayloadSchema.model_validate(data)
            except ValidationError as e:
                log.error(f"Payload validation failed: {e.errors()}")
                raise AgentExecutionError(self.agent_name, f"Invalid payload for action '{action}'.", details=e.errors(), status_code=400)
        else:
            pass

        try:
            if action == "create_sale":
                result_data = await self._create_sale(validated_data, requesting_agent_id, agent_type, context)
            elif action == "get_sale_status":
                result_data = await self._get_sale_status(validated_data, requesting_agent_id, context)
            elif action == "list_recent_sales":
                result_data = await self._list_recent_sales(validated_data, requesting_agent_id, context)
            else:
                raise AgentExecutionError(self.agent_name, f"Action '{action}' routing failed.", status_code=500)

            return result_data

        except HTTPException as http_exc:
            log.warning(f"Action '{action}' failed with HTTP exception: {http_exc.status_code} - {http_exc.detail}")
            raise AgentExecutionError(self.agent_name, http_exc.detail, status_code=http_exc.status_code)
        except (ProductNotFoundError, ClientNotFoundError, InsufficientStockError, LowClientScoreError, DuplicateSaleError, SaleCreationError) as domain_exc:
            log.warning(f"Action '{action}' failed with domain error: {domain_exc}")
            status_code = 409 if isinstance(domain_exc, (InsufficientStockError, LowClientScoreError, DuplicateSaleError)) else \
                          404 if isinstance(domain_exc, (ProductNotFoundError, ClientNotFoundError)) else \
                          400
            raise AgentExecutionError(self.agent_name, str(domain_exc), status_code=status_code)

    async def _create_sale(self, data: CreateSaleActionPayload, agent_id: str, agent_type: SaleAgentType, context: Optional[Dict]) -> Dict:
        service_input = CreateSaleInput(
            client_id=data.client_id,
            agent_id=agent_id,
            agent_type=agent_type,
            items=[CreateSaleItemInput(sku=i['sku'], quantity=i['quantity']) for i in data.items],
            origin_channel=data.origin_channel,
            contextual_note=data.contextual_note,
            currency=data.currency or settings.DEFAULT_CURRENCY,
        )
        created_sale = await self.sales_service.create_sale(service_input)
        return created_sale.model_dump(mode='json', by_alias=True)

    async def _get_sale_status(self, data: GetSaleStatusActionPayload, agent_id: str, context: Optional[Dict]) -> Dict:
        sale = await self.sales_service.get_sale_by_id(data.sale_id)
        return {"sale_id": data.sale_id, "status": sale.status.value}

    async def _list_recent_sales(self, data: ListRecentSalesActionPayload, agent_id: str, context: Optional[Dict]) -> Dict:
        sales_list = await self.sales_service.list_recent_sales_for_user(agent_id, limit=data.limit)
        return {"sales": [s.model_dump(mode='json', by_alias=True) for s in sales_list]}
