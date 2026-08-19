"""
Observability, Prometheus Metrics & OpenTelemetry Package.
Location: src/observability/__init__.py
"""

from .logging import StructuredJsonFormatter, configure_structured_logging
from .metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    get_metrics_registry,
    normalize_route_template,
)
from .middleware import PrometheusMetricsMiddleware
from .tracing import SpanContext, Tracer, generate_span_id, generate_trace_id

__all__ = [
    # Metrics
    "Counter",
    "Gauge",
    "Histogram",
    "MetricsRegistry",
    "get_metrics_registry",
    "normalize_route_template",
    # Tracing
    "SpanContext",
    "Tracer",
    "generate_trace_id",
    "generate_span_id",
    # Middleware & Logging
    "PrometheusMetricsMiddleware",
    "StructuredJsonFormatter",
    "configure_structured_logging",
]
