"""FastAPI Application Factory, Lifespan, and Router Configuration (Spec 6.0 & 6.16)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import AsyncSessionLocal, init_tables
from app.middleware import SecurityHeadersMiddleware, setup_exception_handlers
from app.redis import redis_service
from app.routers.admin import admin_router
from app.routers.auth import router as auth_router
from app.routers.codes import router as codes_router
from app.routers.config_router import router as config_router
from app.routers.devices import router as devices_router
from app.routers.events import router as events_router
from app.routers.health import router as health_router
from app.routers.members import router as members_router
from app.services.config_service import seed_defaults_if_empty
from app.services.fotmob_sync_worker import start_fotmob_worker, stop_fotmob_worker
from app.services.portal_service import seed_portal_templates_if_empty

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown hooks.
    Initializes Redis, database schemas, default config seeds, and FotMob live sync worker.
    """
    # Startup
    await redis_service.init()
    if "sqlite" in settings.DATABASE_URL:
        await init_tables()
    async with AsyncSessionLocal() as session:
        await seed_defaults_if_empty(session)
        await seed_portal_templates_if_empty(session)
        
    start_fotmob_worker()

    yield

    # Shutdown
    stop_fotmob_worker()
    await redis_service.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI ASGI application."""
    app = FastAPI(
        title="DayJournal API",
        version="1.0.0",
        description="Public API and Admin Services for DayJournal ",
        docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url=None,
        lifespan=lifespan
    )

    # 1. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=r"https://.*\.pages\.dev",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "ETag"]
    )

    # 2. Security Headers & Request Correlation Middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 3. Exception Handlers matching Spec 6.1 error catalog
    setup_exception_handlers(app)

    # 4. Mount API Routers
    app.include_router(health_router)
    app.include_router(devices_router)
    app.include_router(codes_router)
    app.include_router(auth_router)
    app.include_router(config_router)
    app.include_router(members_router)
    app.include_router(events_router)
    app.include_router(admin_router)

    return app


app = create_app()
