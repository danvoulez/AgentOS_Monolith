# app/agents/agent_registry.py  
from typing import Dict, Type, Optional, Any, List  
from app.agents.base_agent import BaseAgent, AgentExecutionError  
from app.core.logging_setup import logger \# Use configured logger  
import inspect  
import importlib \# For discovery

class AgentRegistry:  
    """Registers and executes modular AgentOS agents."""  
    def __init__(self):  
        self._agents: Dict\[str, BaseAgent\] \= {}  
        self._common_services: Dict\[str, Any\] \= {} \# Injected common dependencies  
        logger.info("AgentRegistry initialized.")

    def setup_common_services(self, services: Dict\[str, Any\]):  
        """Stores common services to be passed to agents during instantiation."""  
        self._common_services \= services  
        logger.info(f"Common services set for AgentRegistry: {list(services.keys())}")

    def register_agent(self, agent_instance: BaseAgent):  
        """Registers a pre-instantiated agent."""  
        if not agent_instance or not agent_instance.agent_name or agent_instance.agent_name \== "base_agent":  
             logger.error(f"Attempted to register invalid agent instance: {agent_instance}")  
             return  
        if agent_instance.agent_name in self._agents:  
            logger.warning(f"Overwriting agent registration for '{agent_instance.agent_name}'")  
        self._agents\[agent_instance.agent_name\] \= agent_instance  
        logger.info(f"Agent '{agent_instance.agent_name}' registered.")

    def discover_and_register(self, modules_to_scan: List\[str\]):  
         """  
         Automatically discovers BaseAgent subclasses in specified Python modules,  
         instantiates them with common services, and registers them.  
         """  
         log \= logger.bind(discovery_modules=modules_to_scan)  
         log.info("Starting agent discovery and registration...")  
         registered_count \= 0  
         for module_path in modules_to_scan:  
              log_mod \= log.bind(module=module_path)  
              try:  
                   module \= importlib.import_module(module_path)  
                   for name, obj in inspect.getmembers(module):  
                        \# Check if it's a class, subclass of BaseAgent, and not BaseAgent itself  
                        if inspect.isclass(obj) and issubclass(obj, BaseAgent) and obj is not BaseAgent:  
                             log_agent \= log_mod.bind(agent_class=name)  
                             try:  
                                  \# Instantiate the agent, passing common services  
                                  agent_instance \= obj(common_services=self._common_services)  
                                  \# Register using the instance's agent_name  
                                  if hasattr(agent_instance, 'agent_name') and agent_instance.agent_name \!= "base_agent":  
                                       self.register_agent(agent_instance)  
                                       registered_count \+= 1  
                                  else:  
                                       log_agent.error("Agent class does not have a valid 'agent_name' attribute.")  
                             except Exception as e:  
                                  log_agent.exception(f"Failed to instantiate or register agent.")  
              except ImportError as e:  
                   log_mod.error(f"Could not import module for agent discovery: {e}")  
              except Exception as e:  
                  log_mod.exception("Unexpected error during discovery in module.")  
         log.info(f"Agent discovery complete. Total registered agents: {len(self._agents)}")

    async def execute_agent_action(self, agent_name: str, payload: Dict\[str, Any\], context: Optional\[Dict\[str, Any\]\] \= None) \-\> Dict\[str, Any\]:  
        """Finds and executes an action on a registered agent."""  
        log \= logger.bind(agent_name=agent_name, action=payload.get('action'), context=context)  
        log.info("Executing agent action via registry.")

        agent \= self._agents.get(agent_name)  
        if not agent:  
            log.error("Agent not found in registry.")  
            \# Use specific error type defined in base_agent  
            raise AgentExecutionError(agent_name, "Agent not found.", status_code=404)

        try:  
            \# Delegate execution to the agent instance  
            \# The agent's execute method is responsible for validation and logic  
            result_payload \= await agent.execute(payload, context)

            log.info("Agent action executed successfully.")  
            \# Return the result payload directly (MCP Gateway will wrap it in MCPResponse)  
            return result_payload  
        except AgentExecutionError as ae:  
             \# Log and re-raise agent-specific errors  
             log.error(f"Agent execution failed: {ae}. Details: {ae.details}")  
             raise ae  
        except Exception as e:  
             \# Catch unexpected errors during execution  
             log.exception("Unexpected internal error during agent execution.")  
             \# Wrap unexpected errors in AgentExecutionError  
             raise AgentExecutionError(agent_name, f"Unexpected internal error: {e}", status_code=500) from e

    def get_registered_agents(self) \-\> List\[str\]:  
         """Returns a list of names of registered agents."""  
         return list(self._agents.keys())

# \--- Singleton Instance \---  
agent_registry \= AgentRegistry()

# \--- Setup Function (called during app startup) \---  
# Define where your agent implementation modules live  
# Assumes agents are implemented in 'agent.py' within each module directory  
AGENT_MODULE_PATHS \= \[  
    "app.modules.sales.agent",  
    "app.modules.people.agent",  
    "app.modules.delivery.agent", \# Add paths as modules are created  
    "app.modules.llm.agent",  
    \# "app.modules.whatsapp.agent",  
]

def setup_agent_registry(common_services: Dict\[str, Any\]):  
    """Initializes registry with services and discovers agents."""  
    logger.info("Setting up Agent Registry...")  
    agent_registry.setup_common_services(common_services)  
    agent_registry.discover_and_register(AGENT_MODULE_PATHS)  
    logger.info(f"Agent Registry setup complete. Agents loaded: {agent_registry.get_registered_agents()}")
