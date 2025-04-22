# app/main.py \- Final Unified Backend Structure  
from fastapi import FastAPI, Request, status, Depends  
from fastapi.responses import JSONResponse  
from fastapi.exceptions import RequestValidationError  
from starlette.exceptions import HTTPException as StarletteHTTPException  
from contextlib import asynccontextmanager  
import asyncio, uuid, time  
from fastapi.middleware.cors import CORSMiddleware  
from bson import ObjectId \# For index creation if needed  
from slowapi import Limiter, _rate_limit_exceeded_handler \# Import slowapi  
from slowapi.util import get_remote_address  
from slowapi.errors import RateLimitExceeded  
from slowapi.middleware import SlowAPIMiddleware

# \--- Core Imports \---  
from app.core.config import settings  
from app.core.logging_setup import setup_logging, logger, trace_id_middleware \# Use setup \+ middleware  
from app.db.mongo_client import connect_to_mongo, close_mongo_connection, get_database  
from app.core.redis_client import connect_redis, close_redis, get_redis_client  
from app.core.exceptions import ( \# Import custom exceptions  
    LLMError, ModelLoadError, InferenceError, RoutingError, ConfigurationError, CacheError,  
    ProductNotFoundError, ClientNotFoundError, InsufficientStockError, LowClientScoreError,  
    DuplicateSaleError, SaleCreationError, RepositoryError, IntegrationError,  
    QuotaExceededError, PathTraversalError, InvalidFileNameError, FileOperationError  
)  
# Import main API router  
from app.api.v1.api import api_router  
# Import WebSocket listener controls  
from app.websocket.redis_listener import start_websocket_listener, stop_websocket_listener  
# Import Agent Registry setup  
from app.agents.agent_registry import setup_agent_registry  
# Import Pydantic models for error responses  
from app.db.schemas.common_schemas import MsgDetail  
from app.models.api_common import ErrorDetail, ErrorResponse \# Use updated error models

# \--- Configure Logging \---  
setup_logging() \# Call the setup function

# \--- Rate Limiter \---  
# Use client address as key, apply default limits from settings? Or define here.  
# Example: limiter \= Limiter(key_func=get_remote_address, default_limits=\["500/minute"\])  
# For now, initialize without defaults, apply limits per-route.  
limiter \= Limiter(key_func=get_remote_address)

# \--- Custom Exception Handlers \---  
async def http_exception_handler(request: Request, exc: StarletteHTTPException):  
    trace_id \= getattr(request.state, 'trace_id', "N/A")  
    logger.bind(trace_id=trace_id).warning(f"HTTP Exception: Status={exc.status_code}, Detail={exc.detail}")  
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=getattr(exc, "headers", None))

async def validation_exception_handler(request: Request, exc: RequestValidationError):  
    trace_id \= getattr(request.state, 'trace_id', "N/A")  
    log \= logger.bind(trace_id=trace_id)  
    log.warning(f"Validation Error: Path={request.url.path}, Errors={exc.errors()}")  
    \# Format using ErrorDetail model  
    error_details \= \[ErrorDetail(loc=list(e.get('loc', \[\])), msg=e.get('msg', ''), type=e.get('type', 'validation_error')) for e in exc.errors()\]  
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": error_details})

async def generic_domain_exception_handler(request: Request, exc: Exception, status_code: int, log_level: str \= "warning"):  
    """Handles common domain logic exceptions."""  
    trace_id \= getattr(request.state, 'trace_id', "N/A")  
    log_method \= getattr(logger.bind(trace_id=trace_id), log_level)  
    log_method(f"Domain Exception: Type={type(exc).__name__}, Detail={exc}")  
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})

async def repository_error_handler(request: Request, exc: RepositoryError):  
    trace_id \= getattr(request.state, 'trace_id', "N/A")  
    logger.bind(trace_id=trace_id).error(f"Repository/Database Error: {exc}")  
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": "Database operation failed."})

async def integration_error_handler(request: Request, exc: IntegrationError):  
    trace_id \= getattr(request.state, 'trace_id', "N/A")  
    logger.bind(trace_id=trace_id).error(f"Integration Error: {exc}")  
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})

async def llm_error_handler(request: Request, exc: LLMError):  
    trace_id \= getattr(request.state, 'trace_id', "N/A")  
    log \= logger.bind(trace_id=trace_id)  
    status_code \= status.HTTP_500_INTERNAL_SERVER_ERROR; detail \= "LLM processing error."  
    if isinstance(exc, (ModelLoadError, ConfigurationError)): status_code \= status.HTTP_503_SERVICE_UNAVAILABLE; detail \= f"LLM configuration/load error: {exc}"  
    elif isinstance(exc, RoutingError): status_code \= status.HTTP_400_BAD_REQUEST; detail \= f"LLM routing error: {exc}"  
    elif isinstance(exc, InferenceError): status_code \= status.HTTP_502_BAD_GATEWAY; detail \= f"LLM provider error: {exc}"  
    elif isinstance(exc, CacheError): detail \= f"LLM cache error: {exc}"  
    log.error(detail)  
    return JSONResponse(status_code=status_code, content={"detail": detail})

async def file_error_handler(request: Request, exc: Union\[FileOperationError, QuotaExceededError, PathTraversalError, InvalidFileNameError\]):  
     trace_id \= getattr(request.state, 'trace_id', "N/A")  
     log \= logger.bind(trace_id=trace_id)  
     status_code \= status.HTTP_500_INTERNAL_SERVER_ERROR  
     if isinstance(exc, QuotaExceededError): status_code \= status.HTTP_413_REQUEST_ENTITY_TOO_LARGE  
     elif isinstance(exc, (PathTraversalError, InvalidFileNameError)): status_code \= status.HTTP_400_BAD_REQUEST  
     elif isinstance(exc, FileNotFoundError): status_code \= status.HTTP_404_NOT_FOUND \# Need to catch specifically if FileService raises this  
     log.warning(f"File Exception: Type={type(exc).__name__}, Detail={exc}")  
     return JSONResponse(status_code=status_code, content={"detail": str(exc)})

async def generic_unhandled_exception_handler(request: Request, exc: Exception):  
    trace_id \= getattr(request.state, 'trace_id', "N/A")  
    logger.bind(trace_id=trace_id).exception(f"Unhandled Exception: Path={request.url.path}")  
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": "Internal Server Error"}, headers={"X-Trace-ID": trace_id})

# \--- Application Lifespan \---  
@asynccontextmanager  
async def lifespan(app: FastAPI):  
    """Handles startup (connections, index checks, agent registry) and shutdown."""  
    logger.info(f"Starting up {settings.APP_NAME}...")  
    db_instance \= None  
    redis_instance \= None  
    try:  
        \# Connect DB and Redis first  
        await connect_to_mongo()  
        await connect_redis()  
        db_instance \= get_database()  
        redis_instance \= get_redis_client()

        \# \--- Ensure DB Indexes \---  
        logger.info("Ensuring database indexes...")  
        \# Define indexes here for clarity or call a setup function  
        \# Users  
        await db_instance.users.create_index("username", unique=True, background=True)  
        await db_instance.users.create_index("email", unique=True, sparse=True, background=True)  
        \# Memory / Chat Messages  
        mem_coll \= settings.MEMORY_MONGO_COLLECTION  
        await db_instance\[mem_coll\].create_index("chat_id", background=True)  
        await db_instance\[mem_coll\].create_index("timestamp", background=True)  
        await db_instance\[mem_coll\].create_index("is_forgotten", sparse=True, background=True)  
        \# Sales  
        await db_instance.sales.create_index("client_id", background=True)  
        await db_instance.sales.create_index(\[("agent_id", 1), ("created_at", \-1)\], background=True)  
        \# Products  
        await db_instance.products.create_index("sku", unique=True, background=True)  
        await db_instance.products.create_index("is_active", background=True)  
        \# Delivery  
        await db_instance.deliveries.create_index("sale_id", background=True)  
        await db_instance.deliveries.create_index("current_status", background=True)  
        await db_instance.deliveries.create_index("expire_at", expireAfterSeconds=0, background=True) \# TTL  
        \# Audit Logs  
        if settings.AUDIT_LOG_ENABLED:  
            await db_instance\[settings.AUDIT_LOG_MONGO_COLLECTION\].create_index("timestamp", background=True)  
            await db_instance\[settings.AUDIT_LOG_MONGO_COLLECTION\].create_index("actor_id", background=True)  
            await db_instance\[settings.AUDIT_LOG_MONGO_COLLECTION\].create_index("action", background=True)

        logger.info("Database indexes checked/created.")

        \# \--- Setup Agent Registry \---  
        \# Pass essential shared services to the registry setup function  
        common_services \= {"db": db_instance, "redis": redis_instance}  
        setup_agent_registry(common_services)

        \# \--- Start Background Listeners \---  
        if settings.WEBSOCKET_REDIS_LISTENER_ENABLED:  
            await start_websocket_listener() \# Starts the listener task

        logger.info("Startup sequence complete.")  
    except Exception as e:  
        logger.critical(f"Application startup failed: {e}")  
        \# Attempt cleanup on startup failure  
        await close_mongo_connection()  
        await close_redis()  
        if settings.WEBSOCKET_REDIS_LISTENER_ENABLED: await stop_websocket_listener()  
        raise RuntimeError(f"Startup error: {e}") from e

    yield \# Application runs

    logger.info(f"Shutting down {settings.APP_NAME}...")  
    \# Shutdown sequence (listeners first)  
    if settings.WEBSOCKET_REDIS_LISTENER_ENABLED: await stop_websocket_listener()  
    await close_mongo_connection()  
    await close_redis()  
    logger.info("Shutdown complete.")

# \--- FastAPI App \---  
app \= FastAPI(  
    title=settings.APP_NAME,  
    version="1.0.0", \# Consider reading from pyproject.toml or config  
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",  
    docs_url="/docs",  
    redoc_url="/redoc",  
    lifespan=lifespan,  
    exception_handlers={  
        \# FastAPI/Starlette Built-ins  
        StarletteHTTPException: http_exception_handler,  
        RequestValidationError: validation_exception_handler,  
        RateLimitExceeded: _rate_limit_exceeded_handler,  
        \# Custom Domain/Service Errors  
        ProductNotFoundError: lambda r, e: generic_domain_exception_handler(r, e, status.HTTP_404_NOT_FOUND),  
        ClientNotFoundError: lambda r, e: generic_domain_exception_handler(r, e, status.HTTP_404_NOT_FOUND),  
        InsufficientStockError: lambda r, e: generic_domain_exception_handler(r, e, status.HTTP_409_CONFLICT),  
        LowClientScoreError: lambda r, e: generic_domain_exception_handler(r, e, status.HTTP_409_CONFLICT),  
        DuplicateSaleError: lambda r, e: generic_domain_exception_handler(r, e, status.HTTP_409_CONFLICT),  
        SaleCreationError: lambda r, e: generic_domain_exception_handler(r, e, status.HTTP_400_BAD_REQUEST),  
        RepositoryError: repository_error_handler,  
        IntegrationError: integration_error_handler,  
        LLMError: llm_error_handler, \# Handles all LLM exception subtypes  
        QuotaExceededError: lambda r, e: file_error_handler(r, e),  
        PathTraversalError: lambda r, e: file_error_handler(r, e),  
        InvalidFileNameError: lambda r, e: file_error_handler(r, e),  
        FileOperationError: lambda r, e: file_error_handler(r, e),  
        FileNotFoundError: lambda r, e: file_error_handler(r, e), \# Map FileNotFoundError  
        \# Catch-all (must be last)  
        Exception: generic_unhandled_exception_handler,  
    }  
)

# \--- Apply Middlewares \---  
# IMPORTANT: Order matters. Middlewares execute top-down for request, bottom-up for response.

# 1\. Trace ID Middleware (sets trace_id early)  
app.add_middleware(BaseHTTPMiddleware, dispatch=trace_id_middleware)

# 2\. CORS Middleware  
if settings.ALLOWED_ORIGINS:  
    logger.info(f"Configuring CORS for origins: {settings.ALLOWED_ORIGINS}")  
    app.add_middleware(  
        CORSMiddleware,  
        allow_origins=settings.ALLOWED_ORIGINS,  
        allow_credentials=True,  
        allow_methods=\["\*"\],  
        \# Ensure necessary headers are allowed (Authorization, X-CSRF-Token, X-Trace-ID)  
        allow_headers=\["\*", "Authorization", "X-CSRF-Token", "X-Trace-ID"\],  
        expose_headers=\["X-Trace-ID"\] \# Expose trace ID to frontend if needed  
    )

# 3\. Rate Limiting Middleware  
app.state.limiter \= limiter  
app.add_middleware(SlowAPIMiddleware)

# \--- Include API Routers \---  
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# \--- Root Health Check Endpoint \---  
@app.get("/health", tags=\["Health Check"\])  
async def health_check():  
    \# Check dependencies reachable during lifespan/requests  
    \# Simply return OK if app is running  
    return {"status": "healthy", "service": settings.APP_NAME}

# \--- Main Execution Block (for local dev only) \---  
if __name__ \== "__main__":  
    import uvicorn  
    uvicorn.run(  
        "main:app",  
        host=settings.HOST, port=settings.PORT,  
        reload=settings.RELOAD, log_level=settings.LOG_LEVEL.lower()  
    )
