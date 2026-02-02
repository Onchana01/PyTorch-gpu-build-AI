import logging
import logging.config
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from pythonjsonlogger import jsonlogger


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any]
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = datetime.now(timezone.utc).isoformat()
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["module"] = record.module
        log_record["function"] = record.funcName
        log_record["line"] = record.lineno

        if hasattr(record, "build_id"):
            log_record["build_id"] = record.build_id
        if hasattr(record, "pr_number"):
            log_record["pr_number"] = record.pr_number
        if hasattr(record, "gpu_id"):
            log_record["gpu_id"] = record.gpu_id
        if hasattr(record, "rocm_version"):
            log_record["rocm_version"] = record.rocm_version

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)


class ContextFilter(logging.Filter):
    def __init__(self, context: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.context = context or {}

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in self.context.items():
            setattr(record, key, value)
        return True


def get_logging_config(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    json_format: bool = True,
    log_dir: Optional[str] = None
) -> Dict[str, Any]:
    handlers_config = {
        "console": {
            "class": "logging.StreamHandler",
            "level": log_level,
            "stream": "ext://sys.stdout",
        }
    }

    if json_format:
        handlers_config["console"]["formatter"] = "json"
    else:
        handlers_config["console"]["formatter"] = "standard"

    if log_file or log_dir:
        if log_dir:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            log_file = str(log_path / "rocm_cicd.log")

        handlers_config["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": log_level,
            "filename": log_file,
            "maxBytes": 10485760,
            "backupCount": 5,
            "formatter": "json" if json_format else "standard",
        }

    handler_names = list(handlers_config.keys())

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "()": CustomJsonFormatter,
                "format": "%(timestamp)s %(level)s %(name)s %(message)s",
            },
        },
        "handlers": handlers_config,
        "loggers": {
            "": {
                "handlers": handler_names,
                "level": log_level,
                "propagate": True,
            },
            "rocm_cicd": {
                "handlers": handler_names,
                "level": log_level,
                "propagate": False,
            },
            "uvicorn": {
                "handlers": handler_names,
                "level": "INFO",
                "propagate": False,
            },
            "httpx": {
                "handlers": handler_names,
                "level": "WARNING",
                "propagate": False,
            },
        },
    }

    return config


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    json_format: bool = True,
    log_dir: Optional[str] = None
) -> None:
    config = get_logging_config(
        log_level=log_level,
        log_file=log_file,
        json_format=json_format,
        log_dir=log_dir
    )
    logging.config.dictConfig(config)


def get_logger(
    name: str,
    context: Optional[Dict[str, Any]] = None
) -> logging.Logger:
    logger = logging.getLogger(name)

    if context:
        context_filter = ContextFilter(context)
        logger.addFilter(context_filter)

    return logger


class LoggerAdapter(logging.LoggerAdapter):
    def __init__(
        self,
        logger: logging.Logger,
        extra: Optional[Dict[str, Any]] = None
    ):
        super().__init__(logger, extra or {})

    def process(
        self,
        msg: str,
        kwargs: Dict[str, Any]
    ) -> tuple:
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


def get_build_logger(
    build_id: str,
    pr_number: Optional[int] = None,
    rocm_version: Optional[str] = None
) -> LoggerAdapter:
    logger = get_logger("rocm_cicd.build")
    extra = {"build_id": build_id}
    if pr_number:
        extra["pr_number"] = pr_number
    if rocm_version:
        extra["rocm_version"] = rocm_version
    return LoggerAdapter(logger, extra)


def get_analysis_logger(
    failure_id: Optional[str] = None
) -> LoggerAdapter:
    logger = get_logger("rocm_cicd.analysis")
    extra = {}
    if failure_id:
        extra["failure_id"] = failure_id
    return LoggerAdapter(logger, extra)


def get_gpu_logger(
    gpu_id: str,
    gpu_arch: Optional[str] = None
) -> LoggerAdapter:
    logger = get_logger("rocm_cicd.gpu")
    extra = {"gpu_id": gpu_id}
    if gpu_arch:
        extra["gpu_arch"] = gpu_arch
    return LoggerAdapter(logger, extra)
