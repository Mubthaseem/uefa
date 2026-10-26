"""Admin Sub-Routers Aggregation."""

from fastapi import APIRouter

from app.routers.admin.admins import router as admins_router
from app.routers.admin.audit import router as audit_router
from app.routers.admin.auth import router as auth_router
from app.routers.admin.codes import router as codes_router
from app.routers.admin.config_admin import router as config_router
from app.routers.admin.content import router as content_router
from app.routers.admin.devices import router as devices_router
from app.routers.admin.events import router as events_admin_router

admin_router = APIRouter()
admin_router.include_router(auth_router)
admin_router.include_router(codes_router)
admin_router.include_router(devices_router)
admin_router.include_router(config_router)
admin_router.include_router(content_router)
admin_router.include_router(audit_router)
admin_router.include_router(admins_router)
admin_router.include_router(events_admin_router)

__all__ = ["admin_router"]
