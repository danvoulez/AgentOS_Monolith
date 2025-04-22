# app/agents/base_agent.py  
from abc import ABC, abstractmethod  
from typing import Dict, Any, Optional, Type, List  
from pydantic import BaseModel  
from app.core.logging_setup import logger \# Use configured logger

# Import common services/clients potentially needed by agents  
# Avoid direct import if using injected common_services dict  
# from app.services.cache_service import CacheService  
# from app.services.notification_service import NotificationService  
# from app.db.mongo_client import AsyncIOMotorDatabase  
# from app.worker.celery_app import celery_app \# To dispatch tasks

class AgentExecutionError(Exception):  
    """Custom exception for agent action execution failures."""  
    def __init__(self, agent_name: str, message: str, details: Optional\[Any\] \= None, status_code: int \= 500):  
        \# Include status_code suggestion for MCP gateway error mapping  
        super().__init__(message)  
        self.agent_name \= agent_name  
        self.details \= details  
        self.status_code \= status_code \# Suggests appropriate HTTP status if error bubbles up

class BaseAgent(ABC):  
    """Abstract Base Class for all AgentOS modular agents."""  
    \# Subclasses MUST define this unique name  
    agent_name: str \= "base_agent"

    def __init__(self, common_services: Optional\[Dict\[str, Any\]\] \= None):  
        """  
        Initialize agent. Receives shared services injected by the AgentRegistry.  
        Subclasses should call super().__init__(common_services) and then  
        initialize their own specific service/repository dependencies.  
        """  
        self.logger \= logger.bind(agent_name=self.agent_name)  
        \# Store common services if provided  
        self.common_services \= common_services or {}  
        \# Example accessing common services (if registry provides them)  
        \# self.db: Optional\[AsyncIOMotorDatabase\] \= self.common_services.get("db")  
        \# self.redis: Optional\[Any\] \= self.common_services.get("redis")  
        \# self.cache: Optional\[CacheService\] \= self.common_services.get("cache")  
        \# self.notifier: Optional\[NotificationService\] \= self.common_services.get("notifier")  
        self.logger.info("Agent initialized.")

    @abstractmethod  
    async def execute(self, payload: Dict\[str, Any\], context: Optional\[Dict\[str, Any\]\] \= None) \-\> Dict\[str, Any\]:  
        """  
        Main execution method called by the AgentRegistry via MCP.

        Args:  
            payload (Dict\[str, Any\]): Contains 'action' and 'data' for the task.  
                                      'data' should be validated against the action's specific schema.  
            context (Optional\[Dict\[str, Any\]\]): Shared context (user_id, agent_id, roles, trace_id).

        Returns:  
            Dict\[str, Any\]: A dictionary representing the execution result (must be JSON-serializable).  
                            Should align with the 'result' field of MCPResponse.

        Raises:  
            AgentExecutionError: For failures during execution (e.g., validation, business logic, downstream errors).  
                                 Include informative message and optional details.  
        """  
        pass

    \# Optional: Define a dictionary mapping action names to their Pydantic input schemas  
    \# This allows the execute method or registry to perform validation.  
    \# action_schemas: Dict\[str, Type\[BaseModel\]\] \= {}
