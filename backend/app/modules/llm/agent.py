# app/modules/llm/agent.py  
from app.agents.base_agent import BaseAgent, AgentExecutionError  
from typing import Dict, Any, Optional, List, Type  
from pydantic import BaseModel, Field, ValidationError  
from fastapi import Depends, HTTPException, status \# For potential error mapping  
import asyncio \# For running executor in thread

# Import LLM specific components  
from .semantic_llm_executor import SemanticLLMExecutor \# Use the executor  
from app.core.exceptions import LLMError, ConfigurationError, InferenceError, RoutingError \# Import LLM exceptions

# \--- Action Payloads \---  
class InterpretAndExecutePayload(BaseModel):  
    objective: str \= Field(..., description="High-level objective in natural language.")  
    context: Optional\[Dict\[str, Any\]\] \= Field(default_factory=dict)  
    constraints: Optional\[Dict\[str, Any\]\] \= Field(default_factory=dict)  
    \# Flag to control whether the interpreted action should be executed  
    execute_action: bool \= Field(False, description="If true, attempt to execute the interpreted action.")  
    \# Allow specifying output format for interpretation  
    output_format: str \= Field("json", Literal="json", description="Desired format for interpreted payload (currently only JSON).")

class LLMAgent(BaseAgent):  
    """Agent that uses SemanticLLMExecutor to interpret and potentially execute objectives."""  
    agent_name \= "agentos_llm_executor" \# More specific name

    action_schemas: Dict\[str, Optional\[Type\[BaseModel\]\]\] \= {  
        "interpret_and_execute": InterpretAndExecutePayload,  
        \# Add other LLM-specific actions if needed (e.g., 'finetune_model', 'get_llm_status')  
    }

    def __init__(self, common_services: Optional\[Dict\[str, Any\]\] \= None):  
        super().__init__(common_services)  
        \# Initialize the executor (it reads its own config/API keys via settings)  
        try:  
            \# Pass dry_run=True if needed for testing/configuration  
            self.executor \= SemanticLLMExecutor(dry_run=False)  
            self.logger.info("SemanticLLMExecutor initialized for LLMAgent.")  
        except Exception as e:  
             self.logger.exception("Failed to initialize SemanticLLMExecutor for LLMAgent.")  
             \# This is critical, agent cannot function without executor  
             raise RuntimeError(f"LLMAgent dependency initialization failed: {e}") from e

    async def execute(self, payload: Dict\[str, Any\], context: Optional\[Dict\[str, Any\]\] \= None) \-\> Dict\[str, Any\]:  
        """Routes actions to specific methods."""  
        action \= payload.get("action")  
        data \= payload.get("data", {})  
        actor_id \= context.get("agent_id", "unknown_actor") if context else "unknown_actor"

        log \= self.logger.bind(action=action, actor_id=actor_id)  
        log.info("Executing LLM agent action.")

        \# Validate the action payload structure first  
        if not action or action not in self.action_schemas:  
            raise AgentExecutionError(self.agent_name, f"Unsupported action: {action}", status_code=400)

        PayloadSchema \= self.action_schemas\[action\]  
        validated_data: Optional\[BaseModel\] \= None  
        if PayloadSchema:  
            try: validated_data \= PayloadSchema.model_validate(data)  
            except ValidationError as e: raise AgentExecutionError(self.agent_name, f"Invalid payload for '{action}'.", details=e.errors(), status_code=400)

        \# Route to the appropriate method  
        try:  
            if action \== "interpret_and_execute":  
                result_data \= await self._interpret_and_execute(validated_data, context) \# Pass validated Pydantic model  
            else:  
                \# Should be caught by initial check, but safeguard  
                raise AgentExecutionError(self.agent_name, f"Action '{action}' handler not implemented.", status_code=501)

            \# Return the structured result from the action method  
            return result_data

        except AgentExecutionError as ae:  
             raise ae \# Propagate agent errors with status codes  
        except LLMError as le: \# Catch specific LLM errors from executor  
             log.error(f"LLM processing failed: {le}")  
             \# Map LLMError to AgentExecutionError with appropriate code  
             status_code \= 502 if isinstance(le, InferenceError) else \\  
                           503 if isinstance(le, ModelLoadError) else \\  
                           400 if isinstance(le, (ConfigurationError, RoutingError)) else \\  
                           500 \# Default internal error  
             raise AgentExecutionError(self.agent_name, f"LLM operation failed: {le}", status_code=status_code, details=getattr(le, 'details', None)) from le  
        except Exception as e:  
             log.exception(f"Unexpected error executing LLM agent action '{action}'.")  
             raise AgentExecutionError(self.agent_name, f"Internal error during action '{action}'.", details=str(e), status_code=500)

    async def _interpret_and_execute(self, data: InterpretAndExecutePayload, context: Optional\[Dict\]) \-\> Dict:  
        """Handles the 'interpret_and_execute' action."""  
        log \= self.logger.bind(objective=data.objective, execute=data.execute_action)  
        interpreted_payload \= None  
        execution_result \= None

        \# Use asyncio.to_thread for potentially blocking LLM calls and boto3 calls  
        \# within the executor.

        \# 1\. Interpretation Step  
        try:  
            log.info("Running interpretation...")  
            interpreted_payload \= await asyncio.to_thread(  
                 self.executor.run, \# Pass method reference  
                 objective=data.objective,  
                 context=data.context,  
                 constraints=data.constraints,  
                 output_format=data.output_format  
             )  
            \# run() now raises LLMError on failure  
            log.info("Interpretation successful.")  
        except Exception as e:  
             \# Catch errors from run() if not already caught/wrapped by executor  
             log.exception("Interpretation step failed.")  
             raise AgentExecutionError(self.agent_name, f"Failed to interpret objective: {e}", status_code=502) from e \# Use 502 Bad Gateway for upstream LLM failure

        \# 2\. Execution Step (if requested)  
        if data.execute_action:  
            log.info("Executing interpreted payload...")  
            try:  
                 execution_result \= await asyncio.to_thread(  
                     self.executor.execute, \# Pass method reference  
                     interpreted_payload=interpreted_payload,  
                     context=context \# Pass original context if executor needs it  
                 )  
                 \# execute() returns dict with 'status', 'result'/'error'  
                 if execution_result.get("status") \!= "success":  
                      log.error(f"Execution step failed: {execution_result.get('error')}")  
                      \# Raise error with details from execution result  
                      raise AgentExecutionError(  
                          self.agent_name,  
                          f"Execution failed: {execution_result.get('error', 'Unknown execution error')}",  
                          details=execution_result,  
                          status_code=500 \# Default internal error for exec failure  
                      )  
                 log.success("Execution successful.")  
            except Exception as e:  
                 \# Catch errors from execute() or asyncio.to_thread  
                 log.exception("Execution step failed unexpectedly.")  
                 raise AgentExecutionError(self.agent_name, f"Unexpected execution error: {e}", status_code=500) from e

        \# 3\. Log Narrative (after execution attempt)  
        try:  
             await asyncio.to_thread(  
                 self.executor.log_narrative,  
                 data.objective,  
                 interpreted_payload,  
                 execution_result \# Pass execution result (can be None)  
             )  
        except Exception as log_e:  
             log.error(f"Failed to log narrative: {log_e}") \# Don't fail request for logging error

        \# 4\. Return combined result  
        return {  
             "status": "success", \# Overall agent action status  
             "interpretation": interpreted_payload,  
             "execution": execution_result \# Contains its own status and result/error  
        }
