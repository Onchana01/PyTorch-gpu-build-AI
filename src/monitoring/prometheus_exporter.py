from typing import Optional, Dict, Any
from datetime import datetime, timezone
import asyncio

from src.monitoring.metrics_collector import MetricsCollector
from src.common.config.settings import get_settings
from src.common.config.logging_config import get_logger


logger = get_logger(__name__)


class PrometheusExporter:
    def __init__(self, metrics_collector: Optional[MetricsCollector] = None, port: int = 9090):
        self._metrics = metrics_collector or MetricsCollector()
        self._port = port
        self._server = None
        self._running = False
    
    async def start_server(self) -> None:
        try:
            from prometheus_client import start_http_server, REGISTRY
            start_http_server(self._port)
            self._running = True
            logger.info(f"Prometheus metrics server started on port {self._port}")
        except ImportError:
            logger.warning("prometheus_client not installed, using built-in exporter")
            await self._start_builtin_server()
        except Exception as e:
            logger.error(f"Failed to start Prometheus server: {e}")
            raise
    
    async def _start_builtin_server(self) -> None:
        from aiohttp import web
        
        app = web.Application()
        app.router.add_get("/metrics", self._handle_metrics)
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        site = web.TCPSite(runner, "0.0.0.0", self._port)
        await site.start()
        self._running = True
        logger.info(f"Built-in metrics server started on port {self._port}")
    
    async def _handle_metrics(self, request) -> Any:
        from aiohttp import web
        
        metrics_text = await self.export_prometheus()
        return web.Response(text=metrics_text, content_type="text/plain")
    
    async def export_prometheus(self) -> str:
        lines = []
        all_metrics = await self._metrics.get_all_metrics()
        
        for metric in all_metrics:
            name = metric.name.replace(".", "_").replace("-", "_")
            metric_type = str(metric.metric_type).lower()
            
            lines.append(f"# HELP {name} {metric.description or name}")
            lines.append(f"# TYPE {name} {metric_type}")
            
            labels = ""
            if metric.labels:
                label_pairs = [f'{k}="{v}"' for k, v in metric.labels.items()]
                labels = "{" + ",".join(label_pairs) + "}"
            
            lines.append(f"{name}{labels} {metric.value}")
        
        lines.append("")
        lines.append(f"# HELP exporter_timestamp_seconds Timestamp of export")
        lines.append(f"# TYPE exporter_timestamp_seconds gauge")
        lines.append(f"exporter_timestamp_seconds {datetime.now(timezone.utc).timestamp()}")
        
        return "\n".join(lines)
    
    def register_default_metrics(self) -> None:
        self._metrics.register_counter("builds_total", "Total number of builds")
        self._metrics.register_counter("builds_success_total", "Total successful builds")
        self._metrics.register_counter("builds_failed_total", "Total failed builds")
        self._metrics.register_gauge("builds_active", "Currently active builds")
        self._metrics.register_gauge("builds_queued", "Builds waiting in queue")
        self._metrics.register_histogram("build_duration_seconds", "Build duration in seconds")
        self._metrics.register_gauge("gpu_utilization_percent", "GPU utilization percentage")
        self._metrics.register_gauge("gpu_memory_used_bytes", "GPU memory used in bytes")
        
        logger.info("Default Prometheus metrics registered")
    
    async def stop_server(self) -> None:
        self._running = False
        logger.info("Prometheus metrics server stopped")
    
    @property
    def is_running(self) -> bool:
        return self._running
