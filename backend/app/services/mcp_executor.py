import inspect
import asyncio
import uuid # Para trace_id fallback
from typing import Dict, Any, Callable, Optional, Tuple, Type, Annotated
from fastapi import Depends, HTTPException, status
# Use solve_dependencies para resolver Depends() fora do fluxo normal (avançado, usar com cuidado)
# from fastapi.dependencies.utils import solve_dependencies
# from fastapi.routing import APIRoute
from contextlib import asynccontextmanager # Para gerenciar contexto
from pydantic import BaseModel # Para validar parâmetros dinamicamente
import json # Para serialização segura no log

from app.core.logging_config import logger, trace_id_var
from app.services.mcp_registry import mcp_registry # Importa a instância do registro
# Importar dependências comuns que podem ser injetadas
from app.db.mongo_client import get_database, AsyncIOMotorDatabase
from app.core.redis_client import get_redis_client, redis
# Importar CurrentUser corretamente (adaptar ao seu módulo de segurança)
from app.core.security import CurrentUser, UserPublic
# Importar serviços locais (necessários para DI ou instanciação)
from app.services.file_service import FileService
from app.services.user_service import UserService
# Importar clientes de integração
from app.integrations import people_client, sales_client, delivery_client, llm_client
# Importar modelo de auditoria e exceções
from app.db.schemas import AuditLogEntry # Usar o schema Pydantic definido antes
from app.core.exceptions import RepositoryError, IntegrationError # Importar exceções customizadas

# --- Auditoria ---
async def log_audit_event(
    db: AsyncIOMotorDatabase, # Injete o DB
    tool_name: str,
    params: Dict[str, Any],
    user_info: Optional[UserPublic],
    success: bool,
    result: Optional[Any] = None,
    error: Optional[str] = None,
    trace_id: Optional[str] = None,
    duration_ms: Optional[float] = None
):
    """Logs the MCP tool execution attempt to MongoDB 'audit_log' collection."""
    # --- (+) Sanitização de Dados para Log ---
    # NÃO logar senhas, tokens, PII completo nos parâmetros ou resultados!
    # Usar uma função de sanitização (adaptar de agentos_shared ou criar nova)
    def sanitize_log_data(data: Any, depth=0, max_depth=5) -> Any:
        if depth > max_depth: return "*** DEPTH LIMIT ***"
        if isinstance(data, dict):
            safe_dict = {}
            for k, v in data.items():
                k_lower = k.lower()
                if any(secret_key in k_lower for secret_key in ["password", "secret", "token", "key", "authorization", "senha"]):
                    safe_dict[k] = "*** MASKED ***"
                else:
                    safe_dict[k] = sanitize_log_data(v, depth + 1, max_depth)
            return safe_dict
        elif isinstance(data, list):
            return [sanitize_log_data(item, depth + 1, max_depth) for item in data[:50]] # Limitar listas longas
        elif isinstance(data, (str, bytes)) and len(data) > 500: # Limitar strings/bytes longos
            return str(data[:500]) + "... TRUNCATED"
        # Permitir tipos básicos
        elif isinstance(data, (str, int, float, bool, type(None))):
            return data
        # Representação segura para outros tipos
        else:
             return f"<{type(data).__name__}>"

    sanitized_params = sanitize_log_data(params)
    sanitized_result = sanitize_log_data(result) if success else None
    # ------------------------------------------

    log_entry = AuditLogEntry(
        trace_id=trace_id or "no-trace",
        timestamp=datetime.now(timezone.utc),
        user_id=user_info.user_id if user_info else "anonymous/system",
        user_roles=user_info.roles if user_info else [],
        tool_name=tool_name,
        parameters=sanitized_params,
        success=success,
        result=sanitized_result, # Log resultado sanitizado
        error_message=error,
        duration_ms=duration_ms
    )
    try:
        audit_coll = db["audit_log"] # Nome da coleção
        await audit_coll.insert_one(log_entry.model_dump(by_alias=True, exclude_none=True))
        logger.debug("MCP execution audit log created.")
    except Exception as audit_err:
        # Log crítico, mas não deve falhar a execução da ferramenta por causa disso
        logger.exception(f"CRITICAL: Failed to write MCP audit log! Error: {audit_err}")


# --- Executor Principal ---
async def execute_mcp_tool(
    tool_name: str,
    params: Dict[str, Any],
    # Injetar dependências necessárias para o executor e para os handlers
    db: Annotated[AsyncIOMotorDatabase, Depends(get_database)],
    redis: Annotated[Optional[redis.Redis], Depends(get_redis_client)], # Redis é opcional?
    current_user: Annotated[Optional[UserPublic], Depends(CurrentUser)], # Usuário autenticado
    # Injetar serviços locais que podem ser necessários pelos handlers
    # O ideal é que os handlers usem Depends() internamente se possível,
    # mas passá-los aqui pode ser necessário dependendo da estrutura.
    file_service: Annotated[FileService, Depends()],
    user_service: Annotated[UserService, Depends()],
    # Adicionar clientes de integração se os handlers precisarem deles DIRETAMENTE
    # (Melhor se o handler chamar o cliente diretamente)
    # people_api: Annotated[PeopleClient, Depends()],
) -> Dict[str, Any]:
    """
    Executes an MCP tool: finds handler, checks auth, prepares args (basic DI), calls handler, logs audit.
    """
    start_time = time.time()
    trace_id = trace_id_var.get() or f"mcp-exec-{uuid.uuid4()}"
    log = logger.bind(trace_id=trace_id, tool_name=tool_name, mcp_params=params, user_id=current_user.user_id if current_user else "N/A")
    log.info("Executing MCP tool via executor service.")

    audit_success = False
    audit_result = None
    audit_error = None
    handler_instance = None # Para métodos de instância

    try:
        # 1. Obter Handler
        handler_ref = mcp_registry.get_handler(tool_name)
        if not handler_ref:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tool '{tool_name}' not found.")

        # 2. Verificar Permissão (como antes)
        required_roles = TOOL_PERMISSIONS.get(tool_name)
        allowed_roles = required_roles if required_roles is not None else DEFAULT_ALLOWED_ROLES
        if not current_user and allowed_roles is not None:
             raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
        if current_user:
             user_roles = set(current_user.roles or [])
             if not set(allowed_roles).intersection(user_roles):
                 raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not authorized for this tool.")
             log.info("User authorized.")

        # 3. Preparar Handler e Argumentos (Lógica de DI Simplificada)
        call_kwargs = {}
        handler_to_call = handler_ref

        # Tentar detectar se é um método de instância e obter a instância
        # Isso é uma heurística e pode falhar. DI explícita é melhor.
        if inspect.ismethod(handler_ref) and not isinstance(handler_ref.__self__, type):
             # Já é um método vinculado a uma instância (raro no registro)
             handler_to_call = handler_ref
        elif inspect.isfunction(handler_ref) and '.' in getattr(handler_ref, '__qualname__', ''):
             # Provavelmente um método não vinculado. Tentar instanciar a classe.
             qualname_parts = handler_ref.__qualname__.split('.')
             if len(qualname_parts) > 1:
                 class_name = qualname_parts[-2]
                 # Mapeamento classe -> instância/dependência (SIMPLIFICADO)
                 # Idealmente, use o sistema de DI do FastAPI aqui
                 service_map = {
                     "FileService": file_service,
                     "UserService": user_service,
                     "PeopleClient": people_client, # Assumindo instâncias globais/singletons
                     "SalesClient": sales_client,
                     "DeliveryClient": delivery_client,
                     "LLMClient": llm_client,
                 }
                 instance = service_map.get(class_name)
                 if instance:
                      # Recria a referência como um método vinculado à instância
                      handler_to_call = getattr(instance, handler_ref.__name__)
                      log.debug(f"Bound handler to service instance: {class_name}")
                 else:
                      log.warning(f"Could not find instance for class '{class_name}' of tool '{tool_name}'. Assuming static/class method or function.")
                      # Continua assumindo que pode ser chamado sem 'self'

        # Inspecionar a assinatura do handler FINAL que será chamado
        final_signature = inspect.signature(handler_to_call)
        final_params = final_signature.parameters

        # Construir kwargs para a chamada
        for param_name, param in final_params.items():
            if param_name == "self" or param_name == "cls": continue

            if param_name in params:
                call_kwargs[param_name] = params[param_name]
            # Injetar dependências básicas conhecidas pelo executor
            elif param.annotation is AsyncIOMotorDatabase: call_kwargs[param_name] = db
            elif param.annotation is redis.Redis: call_kwargs[param_name] = redis
            elif param.annotation is UserPublic: call_kwargs[param_name] = current_user
            # Adicionar outros mapeamentos explícitos se necessário
            elif param.default is inspect.Parameter.empty:
                log.error(f"Missing required parameter '{param_name}' for tool '{tool_name}'.")
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Missing required parameter: '{param_name}'")

        # Validar parâmetros com Pydantic se o handler tiver anotações
        # (Opcional, idealmente o handler faz isso internamente)

        log.debug(f"Calling handler '{getattr(handler_to_call, '__qualname__', repr(handler_to_call))}' with args: {list(call_kwargs.keys())}")

        # 4. Executar Handler
        if inspect.iscoroutinefunction(handler_to_call):
             tool_result = await handler_to_call(**call_kwargs)
        else:
             tool_result = await asyncio.to_thread(handler_to_call, **call_kwargs)

        audit_success = True
        audit_result = tool_result
        log.success("MCP tool executed successfully.")
        return {"success": True, "result": tool_result}

    except HTTPException as e:
        audit_success = False
        audit_error = f"HTTPException({e.status_code}): {e.detail}"
        log.warning(f"MCP execution failed with HTTPException: {audit_error}")
        raise e # Re-raise para o endpoint
    except (IntegrationError, RepositoryError) as e: # Catch custom errors
         audit_success = False
         audit_error = f"{type(e).__name__}: {e}"
         log.error(f"MCP execution failed due to service/repository error: {audit_error}")
         # Retornar 503 Service Unavailable para erros internos de dependência
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Dependency error for tool '{tool_name}': {e}") from e
    except Exception as e:
        audit_success = False
        audit_error = f"{type(e).__name__}: {e}"
        log.exception(f"MCP execution failed with unexpected error: {audit_error}")
        # Log auditoria ANTES de levantar exceção 500
        await log_audit_event(db, tool_name, params, current_user, audit_success, error=audit_error, trace_id=trace_id, duration_ms=(time.time() - start_time) * 1000)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error executing tool '{tool_name}'. Trace: {trace_id}") from e
    finally:
         # Log de Auditoria (em caso de sucesso ou erro não-HTTPException pego acima)
         if 'e' not in locals() or not isinstance(e, HTTPException):
              duration_ms = (time.time() - start_time) * 1000
              await log_audit_event(db, tool_name, params, current_user, audit_success, result=audit_result, error=audit_error, trace_id=trace_id, duration_ms=duration_ms)
