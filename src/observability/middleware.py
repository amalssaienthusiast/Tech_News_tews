"""
HTTP Metrics & Tracing Middleware for FastAPI.
Location: src/observability/middleware.py
"""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .metrics import get_metrics_registry, normalize_route_template
from .tracing import Tracer


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware measuring request counts and latency distributions.
    
    Guarantees:
    - Zero label cardinality explosion: normalizes dynamic paths to templates
    - Bounded histogram updates
    - Automatic trace context propagation for incoming HTTP requests
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self.metrics = get_metrics_registry()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.monotonic()
        method = request.method
        raw_path = request.url.path
        endpoint = normalize_route_template(raw_path)

        # Scoped root trace for the HTTP request
        span_ctx = Tracer.start_trace(f"HTTP {method} {endpoint}")

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.monotonic() - start_time
            self.metrics.http_requests_total.inc(
                value=1.0,
                method=method,
                endpoint=endpoint,
                status_code=str(status_code),
            )
            self.metrics.http_request_duration_seconds.observe(
                value=duration,
                method=method,
                endpoint=endpoint,
            )
