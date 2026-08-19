"""
Unit & Integration Tests for Observability, Prometheus Metrics & Tracing (Subphase 6E).
Location: tests/test_observability_telemetry.py
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, UTC
import json
import logging
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from src.api.app import app
from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.observability import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    SpanContext,
    StructuredJsonFormatter,
    Tracer,
    get_metrics_registry,
    normalize_route_template,
)
from src.pipeline.runner import CanonicalPipelineRunner

REPO_ROOT = Path(__file__).parent.parent


class TestObservabilityMetrics(unittest.TestCase):
    """Test suite for Prometheus metrics and cardinality safety."""

    def test_route_normalization_bounds_cardinality(self):
        # Dynamic IDs should collapse to template variables
        self.assertEqual(normalize_route_template("/v1/articles/a1b2c3d4e5f67890"), "/v1/articles/{article_id}")
        self.assertEqual(normalize_route_template("/v1/articles/search"), "/v1/articles/search")
        self.assertEqual(normalize_route_template("/v1/events/e1f2a3b4c5d6e7f8"), "/v1/events/{event_id}")
        self.assertEqual(normalize_route_template("/v1/events/active"), "/v1/events/active")
        self.assertEqual(normalize_route_template("/health"), "/health")
        self.assertEqual(normalize_route_template("/metrics"), "/metrics")

    def test_counter_and_gauge_prometheus_rendering(self):
        registry = MetricsRegistry()
        registry.http_requests_total.inc(value=1.0, method="GET", endpoint="/v1/articles", status_code="200")
        registry.queue_depth.set(42)

        rendered = registry.render_prometheus()
        self.assertIn("# TYPE technews_http_requests_total counter", rendered)
        self.assertIn('technews_http_requests_total{endpoint="/v1/articles",method="GET",status_code="200"} 1.0', rendered)
        self.assertIn("# TYPE technews_queue_depth gauge", rendered)
        self.assertIn("technews_queue_depth 42.0", rendered)

    def test_histogram_bucket_distribution(self):
        hist = Histogram("test_latency_seconds", "Test latency", buckets=(0.1, 0.5, 1.0))
        hist.observe(0.05)
        hist.observe(0.25)
        hist.observe(0.75)
        hist.observe(2.0)

        lines = hist.render()
        rendered = "\n".join(lines)
        self.assertIn('test_latency_seconds_bucket{le="0.1"} 1', rendered)
        self.assertIn('test_latency_seconds_bucket{le="0.5"} 2', rendered)
        self.assertIn('test_latency_seconds_bucket{le="1.0"} 3', rendered)
        self.assertIn('test_latency_seconds_bucket{le="+Inf"} 4', rendered)
        self.assertIn("test_latency_seconds_count 4", rendered)


class TestTracingAndCorrelation(unittest.IsolatedAsyncioTestCase):
    """Test suite for OpenTelemetry context propagation and metadata bridge."""

    async def test_trace_context_correlation_metadata(self):
        span_ctx = Tracer.start_trace("zombie_hunt", worker_id="worker_alpha")
        meta = span_ctx.to_correlation_metadata(worker_id="worker_alpha")

        self.assertEqual(meta["trace_id"], span_ctx.trace_id)
        self.assertEqual(meta["span_id"], span_ctx.span_id)
        self.assertEqual(meta["worker_id"], "worker_alpha")
        # Ensure no diagnostic garbage is attached
        self.assertEqual(len(meta), 3)

        # Round-trip reconstruction
        reconstructed = SpanContext.from_metadata(meta, operation_name="pipeline_exec")
        self.assertIsNotNone(reconstructed)
        self.assertEqual(reconstructed.trace_id, span_ctx.trace_id)
        self.assertEqual(reconstructed.span_id, span_ctx.span_id)

    async def test_async_child_span_contextvars_propagation(self):
        root = Tracer.start_trace("root_operation")
        self.assertEqual(Tracer.get_current_context().trace_id, root.trace_id)

        async with Tracer.start_span("child_stage_s01") as child:
            self.assertEqual(child.trace_id, root.trace_id)
            self.assertEqual(child.parent_span_id, root.span_id)
            self.assertNotEqual(child.span_id, root.span_id)
            self.assertEqual(Tracer.get_current_context().span_id, child.span_id)

        # Context restored after exit
        self.assertEqual(Tracer.get_current_context().span_id, root.span_id)


class TestStructuredJsonLogging(unittest.TestCase):
    """Test suite for structured JSON logging formatting."""

    def test_structured_json_log_formatting(self):
        formatter = StructuredJsonFormatter()
        logger = logging.getLogger("test_logger")
        record = logger.makeRecord(
            name="test_logger",
            level=logging.INFO,
            fn="test.py",
            lno=10,
            msg="Observation processed successfully",
            args=(),
            exc_info=None,
        )

        Tracer.start_trace("test_op")
        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        self.assertEqual(parsed["level"], "INFO")
        self.assertEqual(parsed["logger"], "test_logger")
        self.assertEqual(parsed["message"], "Observation processed successfully")
        self.assertIn("trace_id", parsed)
        self.assertIn("timestamp", parsed)


class TestEndToEndTelemetryAPI(unittest.TestCase):
    """Test suite for FastAPI /metrics endpoint and middleware."""

    def setUp(self):
        self.client = TestClient(app)

    def test_metrics_endpoint_exposition(self):
        res = self.client.get("/metrics")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/plain", res.headers["content-type"])
        body = res.text
        self.assertIn("technews_uptime_seconds", body)
        self.assertIn("technews_http_requests_total", body)
        self.assertIn("technews_queue_depth", body)

    def test_observability_architecture_boundaries(self):
        """Ensure observability module has zero storage or SQLite imports."""
        obs_dir = REPO_ROOT / "src" / "observability"
        py_files = [f for f in obs_dir.glob("*.py") if "__pycache__" not in str(f)]

        forbidden = ("sqlite3", "aiosqlite", "src.storage", "storage")
        for py_file in py_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for f in forbidden:
                            self.assertFalse(
                                alias.name == f or alias.name.startswith(f + "."),
                                f"{py_file.name} illegally imports {alias.name}",
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for f in forbidden:
                            self.assertFalse(
                                node.module == f or node.module.startswith(f + "."),
                                f"{py_file.name} illegally imports from {node.module}",
                            )
