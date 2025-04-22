# app/api/v1/endpoints/mcp_gateway.py  
from fastapi import APIRouter, Depends, HTTPException, status, Body  
from typing import Annotated \# Use Annotated for Python 3.9+  
from app.agents.agent_registry import agent_registry \# Import registry instance  
from app.agents.agent_protocol import MCPRequest, MCPResponse, MCPRequestContext \# Import schemas  
from app.agents.base_agent import AgentExecutionError \# Import custom agent error  
from app.core.logging_setup import logger, trace_id_var \# Use configured logger  
from app.core.security import CurrentUser, require_authentication, UserPublic \# Import auth dependencies

router \= APIRouter()

@router.post(  
    "/exec", \# Endpoint path for MCP execution  
    response_model=MCPResponse,  
    summary="Execute Agent Action via MCP",  
    \# Secure this gateway endpoint, require authentication  
    dependencies=\[Depends(require_authentication)\]  
)  
async def execute_mcp_action(  
    \# Use Body(..., embed=True) if you expect {"mcp_request": {...}}  
    \# Otherwise, request body directly matches MCPRequest  
    request: MCPRequest,  
    currentUser: CurrentUser \# Inject authenticated user/agent info  
):  
    """  
    Receives a Machine-to-Machine Command Protocol (MCP) request,  
    validates it, finds the target agent in the registry,  
    enriches context, and executes the requested action.  
    """  
    trace_id \= trace_id_var.get() \# Get trace ID from context var (set by middleware)  
    log \= logger.bind(  
        agent_name=request.agent_name,  
        action=request.payload.action,  
        requesting_agent_id=currentUser.user_id, \# Log who is calling  
        trace_id=trace_id  
    )  
    log.info("MCP Gateway received execution request.")

    \# \--- Prepare Execution Context \---  
    \# Start with context from request, or empty dict  
    exec_context \= request.context.model_dump(exclude_unset=True) if request.context else {}  
    \# Inject/override critical context from the authenticated principal (CurrentUser)  
    exec_context\['agent_id'\] \= currentUser.user_id \# ID of the authenticated caller  
    exec_context\['user_id'\] \= currentUser.user_id \# Assuming agent acts on behalf of itself initially  
    exec_context\['roles'\] \= currentUser.roles \# Roles for potential authorization within agent  
    exec_context\['trace_id'\] \= trace_id \# Ensure trace_id propagation

    try:  
        \# \--- Execute via Registry \---  
        \# Registry handles finding the agent and calling its execute method  
        \# Agent's execute method returns the \*result\* payload  
        result_payload \= await agent_registry.execute_agent_action(  
            agent_name=request.agent_name,  
            payload=request.payload.model_dump(), \# Pass payload dict {action, data}  
            context=exec_context \# Pass enriched context  
        )

        \# \--- Format Success Response \---  
        log.info("MCP action executed successfully by agent.")  
        return MCPResponse(  
            status="success",  
            agent=request.agent_name,  
            action=request.payload.action,  
            result=result_payload, \# Embed the agent's return value here  
            \# explanation=... \# Agent could return this in its result_payload  
        )

    except AgentExecutionError as e:  
        \# Handle errors raised explicitly by the agent or registry  
        log.error(f"Agent execution failed: {e}")  
        \# Map AgentExecutionError to MCPResponse error structure  
        raise HTTPException(  
            status_code=e.status_code, \# Use status code suggested by agent error  
            detail={"message": str(e), "details": e.details} \# Provide structured detail  
        )  
        \# Alternative: Return MCPResponse directly  
        \# return MCPResponse(  
        \#     status="error", agent=e.agent_name, action=request.payload.action,  
        \#     error=str(e), error_details=e.details  
        \# )

    except Exception as e:  
         \# Catch unexpected errors in the gateway itself  
         log.exception("Unexpected error in MCP Gateway during agent execution.")  
         raise HTTPException(  
             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,  
             detail="Internal Server Error processing MCP request."  
         )
