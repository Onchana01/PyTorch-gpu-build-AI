from src.api.routes.health import router as health_router
from src.api.routes.builds import router as builds_router
from src.api.routes.failures import router as failures_router
from src.api.routes.fixes import router as fixes_router
from src.api.routes.metrics import router as metrics_router
from src.api.routes.webhooks import router as webhooks_router

from src.api.routes import health, builds, failures, fixes, metrics, webhooks

__all__ = [
    "health",
    "builds",
    "failures",
    "fixes",
    "metrics",
    "webhooks",
]
