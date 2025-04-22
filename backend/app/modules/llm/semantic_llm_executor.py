# app/modules/llm/semantic_llm_executor.py  
# Implements the Semantic Gateway logic using an external LLM (OpenAI)  
# and includes basic execution routing (initially for AWS EC2).

import json  
from typing import Dict, Optional, Any, List  
from app.core.logging_setup import logger \# Use configured logger  
from app.core.config import settings \# Use unified settings  
from app.core.exceptions import LLMError, ConfigurationError, InferenceError \# Use core exceptions

# Import LLM client (assuming OpenAI for now, could be made dynamic)  
try:  
    from openai import OpenAI, RateLimitError, APIError, Timeout  
    \# TODO: Consider abstracting client usage via agentos-llm-local service call if preferred  
    \# For now, direct OpenAI client usage here for simplicity.  
    if not settings.OPENAI_API_KEY:  
         logger.warning("OPENAI_API_KEY not set in settings. SemanticLLMExecutor using OpenAI will fail.")  
         _openai_client \= None  
    else:  
         _openai_client \= OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)  
except ImportError:  
    _openai_client \= None  
except Exception as e:  
     logger.exception(f"Failed to initialize OpenAI client: {e}")  
     _openai_client \= None

# Import execution library (boto3 for AWS example)  
try:  
    import boto3  
    _boto3_available \= True  
except ImportError:  
    logger.warning("boto3 library not installed. AWS execution actions will fail.")  
    _boto3_available \= False

class SemanticLLMExecutor:  
    """  
    Interprets natural language objectives using an LLM and routes  
    the resulting structured payload to an execution function.  
    """  
    def __init__(self, model: str \= "gpt-4-turbo-preview", dry_run: bool \= False): \# Default to a capable model  
        self.model \= model  
        self.dry_run \= dry_run  
        self.client \= _openai_client \# Use initialized client  
        self.logger \= logger.bind(service="SemanticLLMExecutor", llm_model=model)

        \# \--- Execution Dispatch Table \---  
        \# Maps (service, action) from LLM payload to implementation methods  
        self.execution_map \= {  
            ("ec2", "create_instances"): self._exec_ec2_create,  
            ("s3", "create_bucket"): self._exec_s3_create_bucket, \# Example  
            \# Add more mappings here...  
            \# ("lambda", "invoke_function"): self._exec_lambda_invoke,  
        }  
        if not _boto3_available:  
             self.logger.warning("boto3 not available, disabling AWS execution actions.")  
             \# Remove AWS actions if library missing  
             self.execution_map \= {k:v for k, v in self.execution_map.items() if k\[0\] not in \['ec2', 's3', 'lambda'\]}

    def run(  
        self,  
        objective: str,  
        context: Optional\[Dict\[str, Any\]\] \= None,  
        constraints: Optional\[Dict\[str, Any\]\] \= None,  
        output_format: str \= "json" \# Specify desired output format  
    ) \-\> Dict\[str, Any\]:  
        """  
        Takes an objective and returns an interpreted, structured payload.  
        Does NOT execute the action.  
        """  
        log \= self.logger.bind(objective=objective, context=context, constraints=constraints)  
        log.info("Interpreting objective...")

        if not self.client:  
            log.error("OpenAI client not available for interpretation.")  
            raise ConfigurationError("OpenAI client not initialized. Check API key and library installation.")

        prompt \= self._build_prompt(objective, context, constraints, output_format)

        if self.dry_run:  
            log.info("\[DRY RUN\] Interpretation only.")  
            return {"status": "dry_run", "prompt": prompt, "interpreted_payload": None}

        try:  
            response \= self.client.chat.completions.create(  
                model=self.model,  
                messages=\[{"role": "user", "content": prompt}\],  
                temperature=0.1, \# Low temperature for predictable structured output  
                \# max_tokens=500, \# Limit output size?  
                response_format={"type": "json_object" if output_format \== "json" else "text"}, \# Request JSON output if possible  
            )

            raw_output \= response.choices\[0\].message.content  
            log.debug(f"LLM raw output: {raw_output}")

            \# Parse and validate the structured output  
            interpreted_payload \= self._safe_parse(raw_output, output_format)

            \# Basic validation: check for expected keys like 'action' and 'service'  
            if output_format \== 'json' and not isinstance(interpreted_payload, dict):  
                 raise InferenceError(self.model, f"LLM output was not a valid dictionary/JSON object.")  
            if output_format \== 'json' and ("action" not in interpreted_payload or "service" not in interpreted_payload):  
                 log.warning(f"LLM JSON output missing required 'action' or 'service' keys: {interpreted_payload}")  
                 \# Optionally try to infer or raise error? Raise for now.  
                 raise InferenceError(self.model, "LLM JSON output missing required 'action' or 'service' keys.")

            log.success("Objective interpreted successfully.")  
            return interpreted_payload \# Return the parsed payload dict

        except (RateLimitError, APIError, Timeout) as e:  
             log.error(f"OpenAI API error during interpretation: {e}")  
             raise InferenceError(self.model, f"OpenAI API error: {e}") from e  
        except LLMError as e: \# Catch parsing/validation errors from _safe_parse  
             log.error(f"LLM output processing error: {e}")  
             raise e  
        except Exception as e:  
             log.exception("Unexpected error during LLM interpretation.")  
             raise LLMError(f"Unexpected interpretation error: {e}") from e

    def execute(self, interpreted_payload: Dict\[str, Any\], context: Optional\[Dict\] \= None) \-\> Dict\[str, Any\]:  
        """  
        Executes an action based on the structured payload from the run() method.  
        Uses the dispatch table (self.execution_map).  
        """  
        service \= interpreted_payload.get("service")  
        action \= interpreted_payload.get("action")  
        params \= interpreted_payload.get("params", {})  
        actor \= context.get("agent_id", "unknown") if context else "unknown"

        log \= self.logger.bind(service=service, action=action, actor=actor)  
        log.info("Executing interpreted action...")

        if not service or not action:  
            log.error("Execution failed: Payload missing 'service' or 'action'.")  
            return {"status": "error", "error": "Invalid payload: missing 'service' or 'action'.", "payload": interpreted_payload}

        \# Find handler in dispatch table  
        handler \= self.execution_map.get((service.lower(), action.lower()))

        if not handler:  
            log.error(f"Execution failed: No handler found for service '{service}' and action '{action}'.")  
            return {"status": "error", "error": f"Unsupported action '{action}' for service '{service}'.", "payload": interpreted_payload}

        if self.dry_run:  
            log.info("\[DRY RUN\] Skipping actual execution.")  
            return {"status": "dry_run", "service": service, "action": action, "params": params}

        \# Execute the handler  
        try:  
            \# Pass parameters and potentially context to the handler  
            execution_result \= handler(params, context) \# Make handlers sync for now, wrap in thread if needed  
            log.success(f"Action '{action}' executed successfully.")  
            \# Return standard success format  
            return {"status": "success", "result": execution_result, "service": service, "action": action}  
        except NotImplementedError:  
             log.error("Execution handler not implemented.")  
             return {"status": "error", "error": "Action handler not implemented.", "service": service, "action": action}  
        except Exception as e:  
            log.exception(f"Execution failed for action '{action}'.")  
            \# Return standard error format  
            return {"status": "error", "error": f"Execution error: {e}", "service": service, "action": action}

    def log_narrative(self, objective: str, interpreted_payload: Dict\[str, Any\], execution_result: Optional\[Dict\[str, Any\]\] \= None) \-\> str:  
        """Generates a human-readable narrative log entry."""  
        action \= interpreted_payload.get("action", "N/A")  
        service \= interpreted_payload.get("service", "N/A")  
        params \= interpreted_payload.get("params", {})

        narrative \= f"""  
[NARRATIVA SEMÂNTICA \- Trace: {trace_id_var.get() or 'N/A'}\]  
- Objetivo Recebido: "{objective}"  
- Interpretação LLM: Serviço='{service}', Ação='{action}'  
- Parâmetros Inferidos: {json.dumps(params, indent=2, ensure_ascii=False)}  
"""

        if execution_result:  
            exec_status \= execution_result.get("status", "unknown")  
            if exec_status \== "success":  
                narrative \+= f"- Execução: SUCESSO\\n- Resultado: {json.dumps(execution_result.get('result', {}), indent=2, ensure_ascii=False)}"  
            elif exec_status \== "dry_run":  
                 narrative \+= "- Execução: DRY RUN (Nenhuma ação real realizada)"  
            else: \# Error  
                narrative \+= f"- Execução: FALHA\\n- Erro: {execution_result.get('error', 'Unknown error')}"  
        else:  
            narrative \+= "- Execução: Não solicitada (interpretação apenas)."

        \# Log using standard logger  
        self.logger.info(narrative.strip().replace('\\n', ' ')) \# Log multi-line as single line info  
        return narrative.strip()

    def _build_prompt(self, objective: str, context: Optional\[Dict\], constraints: Optional\[Dict\], fmt: str) \-\> str:  
        """Builds the prompt for the LLM."""  
        prompt \= f"""Your task is to interpret a user's objective, given some context and constraints, and translate it into a precise, executable payload.

User Objective:  
{objective}

Current Context:  
{json.dumps(context or {}, indent=2, ensure_ascii=False)}

Operational Constraints/Policies:  
{json.dumps(constraints or {}, indent=2, ensure_ascii=False)}

Required Output Format:  
- Respond ONLY with a single, valid {fmt.upper()} object.  
- Do NOT include explanations, apologies, or any conversational text outside the {fmt.upper()} structure.  
- The {fmt.upper()} object MUST contain 'service' (e.g., "ec2", "s3", "sales", "database") and 'action' (e.g., "create_instances", "create_bucket", "find_records") keys.  
- Include a 'params' key containing all necessary parameters derived from the objective, context, and constraints. Infer missing parameters logically if possible and safe, otherwise indicate missing parameters if critical.

Example for objective "Create 2 small web servers in Ireland":  
{{  
  "service": "ec2",  
  "action": "create_instances",  
  "params": {{  
    "count": 2,  
    "instance_type": "t3.small", // Inferred "small"  
    "region": "eu-west-1", // Inferred "Ireland"  
    "image_id": "ami-default-linux", // Assume default or request clarification if needed  
    "tags": {{"Purpose": "webserver"}}  
  }}  
}}

Now, process the User Objective based on the Context and Constraints provided above. Respond only with the {fmt.upper()} payload.  
"""  
        return prompt.strip()

    def _safe_parse(self, output: str, fmt: str) \-\> Dict\[str, Any\]:  
        """Safely parses the LLM output string into a dictionary."""  
        log \= self.logger  
        if fmt.lower() \!= "json":  
             log.warning(f"Parsing non-JSON format '{fmt}' is not strictly implemented, returning raw.")  
             \# If needing structured output from non-JSON, add parsing logic here  
             return {"raw_output": output} \# Example for non-JSON

        try:  
            \# Attempt to remove markdown code blocks if present  
            cleaned_output \= output.strip()  
                cleaned_output \= cleaned_output\[7:\]  
                cleaned_output \= cleaned_output\[:-3\]  
            cleaned_output \= cleaned_output.strip()

            \# Parse the cleaned string as JSON  
            parsed \= json.loads(cleaned_output)  
            if not isinstance(parsed, dict):  
                 log.error(f"LLM output parsed but is not a dictionary: {type(parsed)}")  
                 raise LLMError("LLM output is not a valid JSON object.", details={"raw": output})  
            log.debug("LLM output parsed successfully.")  
            return parsed  
        except json.JSONDecodeError as e:  
             log.error(f"Failed to parse LLM output as JSON: {e}. Raw output: {output\[:200\]}...")  
             raise LLMError("LLM output was not valid JSON.", details={"raw": output, "error": str(e)}) from e  
        except Exception as e:  
            log.exception("Unexpected error parsing LLM output.")  
            raise LLMError(f"Unexpected error parsing output: {e}", details={"raw": output}) from e

    \# \--- Execution Handlers (add more as needed) \---

    def _exec_ec2_create(self, params: Dict\[str, Any\], context: Optional\[Dict\] \= None) \-\> Dict\[str, Any\]:  
        """Executes EC2 instance creation via boto3."""  
        log \= self.logger.bind(service="ec2", action="create_instances", params=params)  
        if not _boto3_available: raise NotImplementedError("boto3 library not installed.")

        log.info("Executing EC2 run_instances...")  
        \# \*\*Security:\*\* Validate parameters strictly before passing to boto3\!  
        \# \- Check allowed instance types, regions, AMIs based on constraints/policy.  
        \# \- Sanitize tags.  
        \# \- Apply budget checks.  
        \# Example basic validation:  
        allowed_types \= \["t3.micro", "t3.small"\] \# Load from config/policy  
        if params.get("instance_type") not in allowed_types:  
            raise ValueError(f"Disallowed instance type: {params.get('instance_type')}")  
        \# ... add more validation ...

        try:  
            \# Ensure required params are present  
            region \= params.get("region", "us-east-1") \# Default region?  
            count \= int(params.get("count", 1))  
            instance_type \= params\["instance_type"\] \# Assume required

            ec2 \= boto3.client("ec2", region_name=region)  
            \# Use a safe default AMI or one specified (after validation)  
            ami_id \= "ami-0c55b159cbfafe1f0" \# Example Linux 2 AMI (us-east-1) \- MAKE CONFIGURABLE/VALIDATED

            response \= ec2.run_instances(  
                ImageId=ami_id,  
                InstanceType=instance_type,  
                MinCount=count,  
                MaxCount=count,  
                \# Add TagSpecifications, SecurityGroupIds, KeyName etc. based on params/context/policy  
                \# TagSpecifications=\[{'ResourceType': 'instance', 'Tags': \[{'Key': 'Owner', 'Value': actor_id}\]}\]  
            )  
            instance_ids \= \[inst\["InstanceId"\] for inst in response.get("Instances", \[\])\]  
            log.success(f"EC2 instances created: {instance_ids}")  
            return {"instance_ids": instance_ids} \# Return relevant result  
        except Exception as e:  
            log.exception("boto3 EC2 run_instances failed.")  
            \# Re-raise or wrap in a more specific execution error? Wrap.  
            raise LLMError(f"AWS EC2 execution failed: {e}") from e

    def _exec_s3_create_bucket(self, params: Dict\[str, Any\], context: Optional\[Dict\] \= None) \-\> Dict\[str, Any\]:  
        """Executes S3 bucket creation via boto3."""  
        log \= self.logger.bind(service="s3", action="create_bucket", params=params)  
        if not _boto3_available: raise NotImplementedError("boto3 library not installed.")

        log.info("Executing S3 create_bucket...")  
        \# \*\*Security:\*\* Validate bucket name, region, ACLs, encryption settings.  
        bucket_name \= params.get("bucket_name")  
        region \= params.get("region", "us-east-1") \# S3 region might need specific handling  
        if not bucket_name: raise ValueError("Bucket name is required.")

        \# Add validation for bucket name format/uniqueness if needed

        try:  
            s3 \= boto3.client("s3", region_name=region)  
            \# Handle region constraint for create_bucket  
            location_constraint \= {}  
            if region \!= "us-east-1": \# us-east-1 doesn't use LocationConstraint  
                 location_constraint\['LocationConstraint'\] \= region

            response \= s3.create_bucket(  
                Bucket=bucket_name,  
                CreateBucketConfiguration=location_constraint if location_constraint else None,  
                \# Add ACL, PublicAccessBlock, Encryption based on params/policy  
                \# ObjectLockEnabledForBucket=params.get("object_lock", False)  
            )  
            bucket_location \= response.get("Location")  
            log.success(f"S3 bucket '{bucket_name}' created at {bucket_location}.")  
            return {"bucket_name": bucket_name, "location": bucket_location}  
        except Exception as e:  
            log.exception("boto3 S3 create_bucket failed.")  
            raise LLMError(f"AWS S3 execution failed: {e}") from e

    \# Add more _exec_\* methods here for other services/actions
