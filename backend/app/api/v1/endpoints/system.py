# promptos_backend/app/api/v1/endpoints/system.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime
import os
from app.core.config import settings
from app.services.mcp_registry import mcp_registry
from app.db.mongo_client import get_database, AsyncIOMotorDatabase
from app.core.redis_client import get_redis_client, redis

router = APIRouter()

class StatusResponse(BaseModel):
    project_name: str
    version: str | None
    build_timestamp: str | None
    status: str = "operational"
    database_status: str
    redis_status: str
    registered_mcp_tools: int

APP_VERSION = os.getenv("APP_VERSION", "N/A")
BUILD_TIMESTAMP = os.getenv("BUILD_TIMESTAMP", "N/A")

@router.get("/health", tags=["System"], summary="Basic Health Check")
async def health_check():
    return {"status": "ok"}

@router.get(
    "/status",
    response_model=StatusResponse,
    tags=["System"],
    summary="Detailed Service Status"
)
async def get_system_status(
    db: Annotated[AsyncIOMotorDatabase, Depends(get_database)],
    redis_client: Annotated[redis.Redis | None, Depends(get_redis_client)]
):
    db_status = "unknown"
    try:
        await db.command('ping')
        db_status = "connected"
    except Exception as e:
        logger.error(f"Status Check: DB ping failed: {e}")
        db_status = "error"

    redis_status = "unknown"
    if redis_client:
        try:
            await redis_client.ping()
            redis_status = "connected"
        except Exception as e:
            logger.error(f"Status Check: Redis ping failed: {e}")
            redis_status = "error"
    else:
        redis_status = "not_configured_or_error"

    return StatusResponse(
        project_name=settings.PROJECT_NAME,
        version=APP_VERSION,
        build_timestamp=BUILD_TIMESTAMP,
        database_status=db_status,
        redis_status=redis_status,
        registered_mcp_tools=len(mcp_registry.list_tools())
    )
