from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager
from functools import wraps
import time

from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)

_tracer_provider = None
_tracer = None


def setup_tracing(service_name: str = "rocm-cicd") -> None:
    global _tracer_provider, _tracer
    
    settings = get_settings()
    
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        from opentelemetry.sdk.resources import Resource
        
        resource = Resource.create({"service.name": service_name})
        _tracer_provider = TracerProvider(resource=resource)
        
        if settings.jaeger_endpoint:
            try:
                from opentelemetry.exporter.jaeger.thrift import JaegerExporter
                
                jaeger_exporter = JaegerExporter(
                    agent_host_name=settings.jaeger_endpoint.split(":")[0],
                    agent_port=int(settings.jaeger_endpoint.split(":")[1]) if ":" in settings.jaeger_endpoint else 6831,
                )
                _tracer_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
                logger.info(f"Jaeger tracing enabled: {settings.jaeger_endpoint}")
            except Exception as e:
                logger.warning(f"Failed to initialize Jaeger exporter: {e}")
        
        if settings.debug:
            console_exporter = ConsoleSpanExporter()
            _tracer_provider.add_span_processor(BatchSpanProcessor(console_exporter))
        
        trace.set_tracer_provider(_tracer_provider)
        _tracer = trace.get_tracer(__name__)
        
        logger.info(f"OpenTelemetry tracing initialized for {service_name}")
        
    except ImportError:
        logger.warning("OpenTelemetry not installed, using no-op tracer")
        _tracer = NoOpTracer()


def get_tracer():
    global _tracer
    if _tracer is None:
        setup_tracing()
    return _tracer


class NoOpSpan:
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        logger.debug("NoOpSpan: exiting span context")
    def set_attribute(self, key: str, value: Any) -> None:
        logger.debug(f"NoOpSpan: set_attribute({key}={value})")
    def add_event(self, name: str, attributes: Optional[Dict] = None) -> None:
        logger.debug(f"NoOpSpan: add_event({name})")
    def set_status(self, status) -> None:
        logger.debug(f"NoOpSpan: set_status({status})")
    def record_exception(self, exception: Exception) -> None:
        logger.debug(f"NoOpSpan: record_exception({type(exception).__name__}: {exception})")


class NoOpTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs):
        yield NoOpSpan()
    
    def start_span(self, name: str, **kwargs):
        return NoOpSpan()


def trace_function(span_name: Optional[str] = None):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            name = span_name or func.__name__
            
            with tracer.start_as_current_span(name) as span:
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)
                
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    span.set_attribute("function.success", True)
                    return result
                except Exception as e:
                    span.set_attribute("function.success", False)
                    span.record_exception(e)
                    raise
                finally:
                    duration = time.time() - start_time
                    span.set_attribute("function.duration_ms", duration * 1000)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            name = span_name or func.__name__
            
            with tracer.start_as_current_span(name) as span:
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)
                
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("function.success", True)
                    return result
                except Exception as e:
                    span.set_attribute("function.success", False)
                    span.record_exception(e)
                    raise
                finally:
                    duration = time.time() - start_time
                    span.set_attribute("function.duration_ms", duration * 1000)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def instrument_fastapi(app) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumented for tracing")
    except ImportError:
        logger.warning("opentelemetry-instrumentation-fastapi not installed")
    except Exception as e:
        logger.error(f"Failed to instrument FastAPI: {e}")


import asyncio
