# Routes package for Session AI Backend
# Organizes endpoints by domain

from fastapi import APIRouter

# Import all routers
from backend.routes.auth import router as auth_router
from backend.routes.patients import router as patients_router
from backend.routes.sessions import router as sessions_router
from backend.routes.system import router as system_router


def include_routers(app):
    """Include all routers in the FastAPI app"""
    app.include_router(auth_router)
    app.include_router(patients_router)
    app.include_router(sessions_router)
    app.include_router(system_router)
