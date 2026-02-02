import uvicorn

from src.api.server import create_app
from src.common.config.settings import get_settings
from src.common.config.logging_config import setup_logging, get_logger


def main():
    setup_logging()
    logger = get_logger(__name__)
    settings = get_settings()
    
    app = create_app(debug=settings.debug)
    
    logger.info(f"Starting API server on port {settings.api_port}")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.api_port,
        log_level="info" if not settings.debug else "debug",
    )


if __name__ == "__main__":
    main()
