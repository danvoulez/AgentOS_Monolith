# app/agents/base_agent.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type, List
from pydantic import BaseModel
from app.core.logging_setup import logger

class AgentExecutionError(Exception):
    def __init__(self, agent_name: str, message: str, details: Optional[Any] = None, status_code: int = 500):
        super().__init__(message)
        self.agent_name = agent_name
        self.details = details
        self.status_code = status_code

class BaseAgent(ABC):
    agent_name: str = "base_agent"

    def __init__(self, common_services: Optional[Dict[str, Any]] = None):
        self.logger = logger.bind(agent_name=self.agent_name)
        self.common_services = common_services or {}
        self.logger.info("Agent initialized.")

    @abstractmethod
    async def execute(self, payload: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pass

    action_schemas: Dict[str, Type[BaseModel]] = {}
