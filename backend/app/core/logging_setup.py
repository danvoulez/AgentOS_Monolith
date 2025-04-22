# app/core/logging_setup.py  
import sys  
import logging  
import json \# For JSON formatter  
from loguru import logger  
import contextvars  
import uuid  
from fastapi import Request \# Import Request for middleware if used here

# Import settings safely  
try:  
    from app.core.config import settings  
    LOG_LEVEL \= settings.LOG_LEVEL  
    APP_NAME \= settings.APP_NAME  
except Exception as e:  
    \# Fallback if settings fail to load early  
    LOG_LEVEL \= "INFO"  
    APP_NAME \= "agentos_backend_unknown"  
    print(f"\[Logging Setup Warning\] Could not load settings: {e}. Using defaults.")

# Context variable for trace ID  
trace_id_var: contextvars.ContextVar\[str | None\] \= contextvars.ContextVar("trace_id", default=None)

# \--- Structlog Configuration (Alternative to pure Loguru Formatter) \---  
# Uncomment and install structlog if you prefer its structured logging  
# import structlog  
# def setup_structlog():  
#     structlog.configure(  
#         processors=\[  
#             structlog.contextvars.merge_contextvars,  
#             structlog.stdlib.add_logger_name,  
#             structlog.stdlib.add_log_level,  
#             structlog.processors.TimeStamper(fmt="iso"),  
#             structlog.processors.StackInfoRenderer(),  
#             structlog.processors.format_exc_info,  
#             structlog.processors.UnicodeDecoder(),  
#             \# Render to JSON  
#             structlog.processors.JSONRenderer(serializer=json.dumps),  
#         \],  
#         logger_factory=structlog.stdlib.LoggerFactory(),  
#         wrapper_class=structlog.stdlib.BoundLogger,  
#         cache_logger_on_first_use=True,  
#     )  
#     \# Intercept standard logging for structlog  
#     \# ... (Similar InterceptHandler but targets structlog) ...  
#     logger.info("Structlog configured.")  
# \--- End Structlog Example \---

# \--- Loguru Configuration (Using JSON Sink) \---  
# Custom JSON formatter for Loguru sink  
def serialize_loguru(record):  
    """Custom serializer for Loguru records to produce structured JSON."""  
    subset \= {  
        "timestamp": record\["time"\].isoformat(),  
        "level": record\["level"\].name,  
        "message": record\["message"\],  
        "trace_id": record\["extra"\].get("trace_id", "NO_TRACE_ID"),  
        "service": APP_NAME, \# Add service name  
    }  
    \# Add logger name, function, line details  
    if "name" in record: subset\["logger"\] \= record\["name"\]  
    if "function" in record: subset\["function"\] \= record\["function"\]  
    if "line" in record: subset\["line"\] \= record\["line"\]

    \# Add bound extra context  
    \# Exclude trace_id as it's already handled  
    subset.update({k: v for k, v in record\["extra"\].items() if k \!= "trace_id"})

    \# Handle exception info if present  
    if record\["exception"\]:  
        exc_type, exc_value, tb \= record\["exception"\]  
        subset\["exception"\] \= {  
            "type": exc_type.__name__,  
            "value": str(exc_value),  
            \# Include traceback string if needed (can be long)  
            \# "traceback": "".join(traceback.format_exception(exc_type, exc_value, tb))  
        }  
    return json.dumps(subset, default=str) \# Use default=str for non-serializable types

def sink_serializer(message):  
    """Wrapper function to pass the record to the serializer."""  
    record \= message.record  
    serialized \= serialize_loguru(record)  
    print(serialized, file=sys.stderr) \# Print JSON log to stderr

def setup_logging():  
    """Configure Loguru for structured JSON logging."""  
    logger.remove() \# Remove default handler  
    log_level \= LOG_LEVEL.upper()

    \# Add sink using the custom serializer  
    logger.add(  
        sink_serializer, \# Use the custom sink function  
        level=log_level,  
        enqueue=True, \# Async logging  
        \# No format needed here as serializer handles it  
        \# format="{message}", \# Minimal format if needed? No, serializer does it.  
    )

    \# Intercept standard logging (similar handler as before, routes to Loguru)  
    class InterceptHandler(logging.Handler):  
        def emit(self, record: logging.LogRecord):  
            try: level \= logger.level(record.levelname).name  
            except ValueError: level \= record.levelno  
            frame \= logging.currentframe(); depth \= 0  
            \# Find correct stack frame  
            while frame and frame.f_code.co_filename \== logging.__file__:  
                frame \= frame.f_back; depth \+= 1  
            if frame is None: frame \= logging.currentframe(); depth \= 0  
            \# Get trace_id from context var  
            trace_id \= trace_id_var.get() \# Loguru extra will pick this up if bound  
            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=\[InterceptHandler()\], level=0, force=True)

    \# Configure log levels for noisy libraries (optional)  
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING if log_level \!= "DEBUG" else logging.INFO)  
    logging.getLogger("multipart").setLevel(logging.INFO)

    logger.info(f"Structured JSON logging configured. Level: {log_level}. Service: {APP_NAME}")

# Middleware to manage trace_id context variable (can be in main.py)  
async def trace_id_middleware(request: Request, call_next):  
    """Sets and resets the trace_id context variable for each request."""  
    trace_id \= request.headers.get("X-Trace-ID", str(uuid.uuid4()))  
    request.state.trace_id \= trace_id \# Make accessible on request state  
    token \= trace_id_var.set(trace_id) \# Set for loguru formatter/serializer

    response \= await call_next(request)

    trace_id_var.reset(token) \# Reset context var  
    response.headers\["X-Trace-ID"\] \= trace_id \# Ensure header is on response  
    return response
