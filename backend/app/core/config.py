# app/core/config.py  
from pydantic_settings import BaseSettings, SettingsConfigDict  
from pydantic import Field  
from pathlib import Path  
from loguru import logger  
from typing import Optional, List, Dict, Any  
import json, re

# \--- Constants \---  
DEFAULT_SAFE_FILENAME_REGEX \= r"^\[a-zA-Z0-9_.-\]+$"

# \--- Pydantic Models \---  
class ModelConfig(BaseModel): \# For LLM Module if included  
    name: str \= Field(...)  
    provider: str \= Field(...)  
    model_id: str \= Field(...)  
    api_base: Optional\[str\] \= None  
    api_key_env_var: Optional\[str\] \= None  
    device: Optional\[str\] \= None  
    max_context_tokens: int \= 2048

class Settings(BaseSettings):  
    \# \--- Core App Settings \---  
    APP_NAME: str \= "AgentOS Unified Backend"  
    API_V1_PREFIX: str \= "/api/v1"  
    LOG_LEVEL: str \= "INFO"  
    \# Generate a strong secret: openssl rand \-hex 32  
    SECRET_KEY: str \= Field(..., description="Secret key for JWT signing \- REQUIRED")

    \# \--- Authentication \---  
    ALGORITHM: str \= "HS256"  
    ACCESS_TOKEN_EXPIRE_MINUTES: int \= 60 \* 24 \# 1 day token expiry? Adjust as needed

    \# \--- CORS \---  
    \# Example: "http://localhost:5173,https://your-fusion-app.com"  
    ALLOWED_ORIGINS: List\[str\] \= Field(\["\*"\], description="List of allowed CORS origins. Use '\*' for dev ONLY.")

    \# \--- Database (MongoDB) \---  
    MONGODB_URI: str \= Field(..., description="MongoDB connection string \- REQUIRED")  
    MONGO_DB_NAME: Optional\[str\] \= None \# Derived from URI if not set, defaults to 'agentos_db'

    \# \--- Redis (Cache, Pub/Sub, Celery Backend/Broker, Sessions) \---  
    REDIS_URL: str \= Field(..., description="Redis connection string \- REQUIRED")  
    REDIS_PASSWORD: Optional\[str\] \= None

    \# \--- Celery \---  
    CELERY_BROKER_URL: Optional\[str\] \= None \# Derived from REDIS_URL (DB 1\) if not set  
    CELERY_RESULT_BACKEND: Optional\[str\] \= None \# Derived from REDIS_URL (DB 2\) if not set  
    PROMPTOS_TASK_QUEUE: str \= "promptos_tasks" \# Example queue for complex tasks

    \# \--- Memory Settings \---  
    MEMORY_CACHE_ENABLED: bool \= True  
    MEMORY_REDIS_MAX_HISTORY: int \= 20  
    MEMORY_REDIS_TTL_SECONDS: int \= 3600 \* 24 \# 1 day  
    MEMORY_REDIS_KEY_PREFIX: str \= "chat_memory:"  
    MEMORY_MONGO_COLLECTION: str \= "chat_messages"  
    AGENT_USE_VECTOR_MEMORY: bool \= False \# Requires Atlas setup  
    STORE_AGENT_EMBEDDINGS: bool \= False \# Requires OpenAI key and processing  
    OPENAI_EMBEDDING_MODEL: str \= "text-embedding-3-small"  
    ATLAS_VECTOR_INDEX_NAME: str \= "embedding_vector_index" \# Ensure this index exists  
    ATLAS_VECTOR_NUM_CANDIDATES: int \= 50  
    ATLAS_VECTOR_LIMIT: int \= 5  
    MEMORY_MASK_PII: bool \= False \# Requires PII detection logic

    \# \--- Audit Log Settings \---  
    AUDIT_LOG_ENABLED: bool \= True  
    AUDIT_LOG_MONGO_COLLECTION: str \= "audit_logs"

    \# \--- WebSocket / PubSub \---  
    WEBSOCKET_REDIS_LISTENER_ENABLED: bool \= True  
    \# Channels the main backend listens to for broadcasting via WebSocket  
    \# These are published BY Vox or other internal services  
    REDIS_LISTEN_CHANNELS: List\[str\] \= Field(  
        \["vox.\*", "user.\*", "task.\*"\], \# Listen to Vox updates, user-specific events, task updates  
        description="List of Redis Pub/Sub channel patterns to listen to for WS broadcast."  
    )  
    \# Channel this backend publishes events TO (for Vox or other listeners)  
    BACKEND_PUBLISH_EVENT_CHANNEL: str \= "backend.events"

    \# \--- File Management \---  
    USER_FILES_BASE_PATH: str \= "/data/user_files" \# Needs persistent volume in prod  
    USER_DEFAULT_QUOTA_BYTES: int \= 100 \* 1024 \* 1024 \# 100 MB  
    USER_MAX_UPLOAD_SIZE_BYTES: int \= 50 \* 1024 \* 1024 \# 50 MB  
    USER_SAFE_FILENAME_REGEX: str \= DEFAULT_SAFE_FILENAME_REGEX

    \# \--- CSRF Protection (for Fusion App direct interactions) \---  
    CSRF_ENABLED: bool \= True \# Enable CSRF check middleware/dependency  
    CSRF_COOKIE_SAMESITE: str \= "lax"  
    CSRF_COOKIE_SECURE: bool \= True \# MUST be True for HTTPS production  
    CSRF_COOKIE_HTTPONLY: bool \= True

    \# \--- LLM Module Configuration (if llm module is included) \---  
    LLM_MODELS_CONFIG_JSON: str \= Field('\[\]', description='JSON string list of ModelConfig for LLM module.')  
    LLM_ROUTING_RULES_JSON: str \= Field('\[\]', description='JSON string list of routing rules for LLM module.')  
    LLM_DEFAULT_LOCAL_ALIAS: Optional\[str\] \= None  
    LLM_DEFAULT_EXTERNAL_ALIAS: Optional\[str\] \= None  
    \# API Keys needed by LLM module models  
    OPENAI_API_KEY: Optional\[str\] \= None  
    ANTHROPIC_API_KEY: Optional\[str\] \= None

    \# \--- Integration URLs/Keys (Specific to modules using them) \---  
    PEOPLE_SERVICE_URL: Optional\[str\] \= None \# Not needed if people module is internal  
    SALES_SERVICE_URL: Optional\[str\] \= None \# Not needed if sales module is internal  
    BANKING_API_KEY: Optional\[str\] \= None  
    DELIVERY_API_KEY: Optional\[str\] \= None  
    META_APP_SECRET: Optional\[str\] \= None \# If whatsapp module is internal  
    META_ACCESS_TOKEN: Optional\[str\] \= None \# If whatsapp module is internal  
    META_PHONE_NUMBER_ID: Optional\[str\] \= None \# If whatsapp module is internal

    \# \--- Gunicorn \---  
    GUNICORN_BIND: Optional\[str\] \= "0.0.0.0:8000"  
    GUNICORN_WORKERS: Optional\[int\] \= None  
    GUNICORN_WORKER_CLASS: str \= "uvicorn.workers.UvicornWorker"

    \# Parsed Models/Rules/Keys from JSON/Env  
    LLM_MODELS: List\[ModelConfig\] \= \[\]  
    LLM_ROUTING_RULES: List\[Dict\[str, Any\]\] \= \[\]  
    LLM_LOADED_API_KEYS: Dict\[str, str\] \= {}

    model_config \= SettingsConfigDict(  
        env_file=str(Path.cwd() / ".env"), \# Single .env file at the root  
        env_file_encoding="utf-8",  
        extra="ignore",  
        case_sensitive=False,  
    )

    @model_validator(mode='after')  
    def process_and_validate(self) \-\> 'Settings':  
        \# Derive DB name if needed  
        if self.MONGO_DB_NAME is None and self.MONGODB_URI:  
            try:  
                db_name \= self.MONGODB_URI.split('/')\[-1\].split('?')\[0\]  
                self.MONGO_DB_NAME \= db_name if db_name else "agentos_db"  
            except Exception: self.MONGO_DB_NAME \= "agentos_db"  
            logger.info(f"Derived MONGO_DB_NAME: {self.MONGO_DB_NAME}")

        \# Derive Celery URLs if needed  
        if self.CELERY_BROKER_URL is None and self.REDIS_URL:  
            try: self.CELERY_BROKER_URL \= f"{self.REDIS_URL.rsplit('/', 1)\[0\]}/1"  
            except Exception: logger.warning("Could not derive default CELERY_BROKER_URL")  
        if self.CELERY_RESULT_BACKEND is None and self.REDIS_URL:  
             try: self.CELERY_RESULT_BACKEND \= f"{self.REDIS_URL.rsplit('/', 1)\[0\]}/2"  
             except Exception: logger.warning("Could not derive default CELERY_RESULT_BACKEND")

        \# Parse LLM Config JSON  
        try:  
            models_list \= json.loads(self.LLM_MODELS_CONFIG_JSON)  
            self.LLM_MODELS \= \[ModelConfig(\*\*cfg) for cfg in models_list\]  
        except Exception as e:  
            logger.error(f"Failed to parse LLM_MODELS_CONFIG_JSON: {e}")  
            raise ValueError("Invalid LLM_MODELS_CONFIG_JSON") from e  
        try:  
            self.LLM_ROUTING_RULES \= json.loads(self.LLM_ROUTING_RULES_JSON)  
        except Exception as e:  
            logger.warning(f"Failed to parse LLM_ROUTING_RULES_JSON: {e}")  
            self.LLM_ROUTING_RULES \= \[\]

        \# Load required API keys for configured LLM models  
        for model_cfg in self.LLM_MODELS:  
            if model_cfg.api_key_env_var:  
                key \= getattr(self, model_cfg.api_key_env_var, None)  
                if not key:  
                    raise ValueError(f"API key env var '{model_cfg.api_key_env_var}' not set for model '{model_cfg.name}'.")  
                self.LLM_LOADED_API_KEYS\[model_cfg.api_key_env_var\] \= key

        \# Validate required secrets  
        if not self.SECRET_KEY: raise ValueError("SECRET_KEY environment variable is required.")  
        if not self.MONGODB_URI: raise ValueError("MONGODB_URI environment variable is required.")  
        if not self.REDIS_URL: raise ValueError("REDIS_URL environment variable is required.")  
        if not self.CELERY_BROKER_URL: raise ValueError("CELERY_BROKER_URL required (explicitly or derived from REDIS_URL).")  
        if not self.CELERY_RESULT_BACKEND: raise ValueError("CELERY_RESULT_BACKEND required (explicitly or derived from REDIS_URL).")

        \# Convert comma-separated origins to list  
        if isinstance(self.ALLOWED_ORIGINS, str):  
            self.ALLOWED_ORIGINS \= \[o.strip() for o in self.ALLOWED_ORIGINS.split(',') if o.strip()\]  
        if isinstance(self.REDIS_LISTEN_CHANNELS, str):  
            self.REDIS_LISTEN_CHANNELS \= \[c.strip() for c in self.REDIS_LISTEN_CHANNELS.split(',') if c.strip()\]

        return self

# \--- Global Settings Instance \---  
try:  
    settings \= Settings()  
    logger.info(f"Settings loaded for {settings.APP_NAME}")  
    logger.info(f"Log Level: {settings.LOG_LEVEL}")  
    logger.info(f"MongoDB DB: {settings.MONGO_DB_NAME}")  
    logger.info(f"Redis Connected: {settings.REDIS_URL.split('@')\[-1\] if '@' in settings.REDIS_URL else settings.REDIS_URL}")  
    logger.info(f"CORS Origins: {settings.ALLOWED_ORIGINS}")  
    logger.info(f"Memory Cache: {'Enabled' if settings.MEMORY_CACHE_ENABLED else 'Disabled'}")  
    logger.info(f"Audit Log: {'Enabled' if settings.AUDIT_LOG_ENABLED else 'Disabled'}")  
    logger.info(f"WebSocket Listener: {'Enabled' if settings.WEBSOCKET_REDIS_LISTENER_ENABLED else 'Disabled'}")  
    logger.info(f"LLM Models Configured: {len(settings.LLM_MODELS)}")  
except ValueError as e:  
    logger.critical(f"CONFIGURATION ERROR: {e}")  
    import sys  
    sys.exit(f"Configuration Error: {e}")  
except Exception as e:  
     logger.critical(f"Unexpected error loading settings: {e}")  
     import sys  
     sys.exit(f"Unexpected Settings Error: {e}")

# Compile safe filename regex  
try:  
    safe_filename_pattern \= re.compile(settings.USER_SAFE_FILENAME_REGEX)  
except re.error as e:  
    logger.error(f"Invalid USER_SAFE_FILENAME_REGEX: '{settings.USER_SAFE_FILENAME_REGEX}'. Using default. Error: {e}")  
    safe_filename_pattern \= re.compile(DEFAULT_SAFE_FILENAME_REGEX)  
