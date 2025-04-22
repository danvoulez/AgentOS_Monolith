# app/agents/agent_protocol.py  
from pydantic import BaseModel, Field  
from typing import Dict, Any, Optional, List

# \--- MCP Request Components \---

class MCPRequestPayload(BaseModel):  
    """Schema for the data payload sent TO an agent via MCP."""  
    action: str \= Field(..., description="The specific action the agent should perform (e.g., 'create_sale', 'get_stock').")  
    data: Dict\[str, Any\] \= Field(default_factory=dict, description="Data/parameters required for the action, validated by the agent's specific action schema.")

class MCPRequestContext(BaseModel):  
    """Optional context sent with the MCP request, usually populated by the gateway."""  
    trace_id: Optional\[str\] \= None  
    user_id: Optional\[str\] \= None \# ID of the user initiating the original request (if any)  
    agent_id: Optional\[str\] \= None \# ID of the AgentOS agent (e.g., JWT sub) making the MCP call  
    roles: List\[str\] \= Field(default_factory=list) \# Roles of the calling agent/user  
    session_id: Optional\[str\] \= None \# e.g., chat_id or other session identifier  
    \# Add other potentially useful context

class MCPRequest(BaseModel):  
    """The overall structure for an MCP request to the /mcp/exec gateway."""  
    agent_name: str \= Field(..., description="The registered name of the target agent (e.g., 'agentos_sales').")  
    payload: MCPRequestPayload  
    context: Optional\[MCPRequestContext\] \= None

# \--- MCP Response \---

class MCPResponse(BaseModel):  
    """Standard response structure from an agent execution via MCP."""  
    status: str \= Field(..., examples=\["success", "error"\], description="Indicates if the action execution was successful.")  
    agent: str \# Name of the agent that executed  
    action: str \# Action that was executed  
    result: Optional\[Any\] \= Field(None, description="Payload returned by the agent on success (can be any JSON-serializable type).")  
    explanation: Optional\[str\] \= Field(None, description="Optional human-readable explanation of the action/result.")  
    error: Optional\[str\] \= Field(None, description="Concise error message if status is 'error'.")  
    error_details: Optional\[Any\] \= Field(None, description="Detailed error information (e.g., validation errors, stack trace snippet in dev).")
