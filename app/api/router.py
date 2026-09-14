from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.support import router as support_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(support_router)
