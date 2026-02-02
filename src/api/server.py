from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import builds, failures, fixes, metrics, health, webhooks
from src.api.middleware.auth_middleware import AuthMiddleware
from src.api.middleware.rate_limiter import RateLimiter
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ROCm CI/CD API server")
    yield
    logger.info("Shutting down ROCm CI/CD API server")


def create_app(
    title: str = "ROCm CI/CD Pipeline API",
    version: str = "1.0.0",
    debug: bool = False,
) -> FastAPI:
    settings = get_settings()
    
    app = FastAPI(
        title=title,
        version=version,
        description="ROCm-Accelerated PyTorch CI/CD Pipeline API",
        debug=debug,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RateLimiter)
    
    app.include_router(health.router, prefix="/api/v1", tags=["Health"])
    app.include_router(builds.router, prefix="/api/v1", tags=["Builds"])
    app.include_router(failures.router, prefix="/api/v1", tags=["Failures"])
    app.include_router(fixes.router, prefix="/api/v1", tags=["Fixes"])
    app.include_router(metrics.router, prefix="/api/v1", tags=["Metrics"])
    app.include_router(webhooks.router, prefix="/api/v1", tags=["Webhooks"])
    
    logger.info(f"API server configured: {title} v{version}")
    
    return app


app = create_app()
