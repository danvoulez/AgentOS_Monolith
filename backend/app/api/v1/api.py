# backend/app/api/v1/api.py

from fastapi import APIRouter

from app.api.v1.endpoints import system

api_router = APIRouter()

api_router.include_router(system.router, tags=["System"])
