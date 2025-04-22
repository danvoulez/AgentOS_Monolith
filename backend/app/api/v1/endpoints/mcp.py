from fastapi import APIRouter, Depends, HTTPException, status, Body
from typing import Dict, Any, Annotated, List
from pydantic import BaseModel, Field

from app.core.logging_config import logger
from app.core.security import CurrentUser, UserPublic, require_authentication
from app.services.mcp_executor import execute_mcp_tool
from app.services.mcp_registry import mcp_registry
from app.core.csrf_utils import verify_csrf_token

router = APIRouter()

CSRFProtected = Depends(verify_csrf_token)
AuthenticatedUser = Depends(require_authentication)

class MCPExecutionRequest(BaseModel):
    tool_name: str = Field(..., description="The unique name of the tool to execute (e.g., 'vendas.create_sale').")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameters required by the tool.")

@router.post(
    "/execute",
    summary="Execute an MCP Tool",
    description="Executes a registered MCP tool by name with given parameters. Requires authentication and CSRF token.",
    dependencies=[AuthenticatedUser, CSRFProtected]
)
async def execute_tool_endpoint(
    request_body: MCPExecutionRequest = Body(...),
    current_user: CurrentUser = Depends()
):
    log = logger.bind(tool_name=request_body.tool_name, user_id=current_user.user_id)
    log.info("Received request to execute MCP tool via API.")

    try:
        result_dict = await execute_mcp_tool(
            tool_name=request_body.tool_name,
            params=request_body.parameters,
            current_user=current_user
        )
        return result_dict

    except HTTPException as e:
        log.warning(f"MCP endpoint failed with HTTPException: Status={e.status_code}, Detail={e.detail}")
        raise e
    except Exception as e:
        log.exception("Unexpected error in MCP execute endpoint.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error processing MCP request."
        )

@router.get(
    "/tools",
    response_model=List[str],
    summary="List Available MCP Tools",
    dependencies=[AuthenticatedUser]
)
async def list_mcp_tools():
    log = logger.bind(action="list_mcp_tools")
    try:
        tool_names = mcp_registry.list_tools()
        log.info(f"Returning {len(tool_names)} registered MCP tools.")
        return tool_names
    except Exception as e:
        log.exception("Failed to retrieve list of MCP tools.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve available tools."
        )
