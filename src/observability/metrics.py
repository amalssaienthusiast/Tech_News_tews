"""
Prometheus Metrics Registry and Telemetry Primitives.
Location: src/observability/metrics.py

Provides bounded, cardinality-safe Prometheus metric collectors:
- Counters, Gauges, and Histograms with bounded label values
- Zero dynamic IDs (URLs, article IDs, trace IDs) in metric labels
- Thread/async-safe atomic updates
- Prometheus exposition format generator
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple


# Default latency histogram buckets (in seconds)
DEFAULT_LATENCY_BUCKETS: Tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0
)

# Endpoint normalizer to prevent URL cardinality explosion
_UUID_OR_HEX_PATTERN = re.compile(r'/[0-9a-fA-F-]{8,}')
_INT_ID_PATTERN = re.compile(r'/\d+')


def normalize_route_template(path: str) -> str:
    """Normalize dynamic URL paths to static route templates to prevent label explosion."""
    if not path or path == "/":
        return "/"
    # Clean query parameters if present
    clean_path = path.split("?")[0].rstrip("/")
    if not clean_path:
        return "/"
    
    # Specific known route patterns
    if clean_path.startswith("/v1/articles/") and clean_path != "/v1/articles/search":
        return "/v1/articles/{article_id}"
    if clean_path.startswith("/v1/events/") and clean_path != "/v1/events/active":
        return "/v1/events/{event_id}"
    
    # General ID sanitization
    normalized = _UUID_OR_HEX_PATTERN.sub("/{id}", clean_path)
    normalized = _INT_ID_PATTERN.sub("/{id}", normalized)
    return normalized


def _format_labels(labels: Dict[str, str]) -> str:
    """Format dictionary into Prometheus label syntax: {key="val",...}"""
    if not labels:
        return ""
    pairs = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(pairs) + "}"


class Counter:
    """Prometheus Counter (monotonically increasing)."""

    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._values: Dict[Tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, value: float = 1.0, **labels: str) -> None:
        if value < 0:
            raise ValueError("Counter increments must be non-negative")
        key = tuple(str(labels.get(ln, "")) for ln in self.label_names)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value

    def get(self, **labels: str) -> float:
        key = tuple(str(labels.get(ln, "")) for ln in self.label_names)
        with self._lock:
            return self._values.get(key, 0.0)

    def render(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            if not self.label_names:
                val = self._values.get((), 0.0)
                lines.append(f"{self.name} {val}")
            else:
                for key, val in sorted(self._values.items()):
                    lbl_dict = dict(zip(self.label_names, key))
                    lines.append(f"{self.name}{_format_labels(lbl_dict)} {val}")
        return lines


class Gauge:
    """Prometheus Gauge (arbitrary instantaneous value)."""

    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._values: Dict[Tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **labels: str) -> None:
        key = tuple(str(labels.get(ln, "")) for ln in self.label_names)
        with self._lock:
            self._values[key] = float(value)

    def inc(self, value: float = 1.0, **labels: str) -> None:
        key = tuple(str(labels.get(ln, "")) for ln in self.label_names)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + float(value)

    def dec(self, value: float = 1.0, **labels: str) -> None:
        key = tuple(str(labels.get(ln, "")) for ln in self.label_names)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - float(value)

    def get(self, **labels: str) -> float:
        key = tuple(str(labels.get(ln, "")) for ln in self.label_names)
        with self._lock:
            return self._values.get(key, 0.0)

    def render(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            if not self.label_names:
                val = self._values.get((), 0.0)
                lines.append(f"{self.name} {val}")
            else:
                for key, val in sorted(self._values.items()):
                    lbl_dict = dict(zip(self.label_names, key))
                    lines.append(f"{self.name}{_format_labels(lbl_dict)} {val}")
        return lines


class Histogram:
    """Prometheus Histogram (cumulative bucket distributions + count + sum)."""

    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_LATENCY_BUCKETS,
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self.buckets = tuple(sorted(buckets))
        self._counts: Dict[Tuple[str, ...], int] = {}
        self._sums: Dict[Tuple[str, ...], float] = {}
        self._bucket_counts: Dict[Tuple[str, ...], List[int]] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **labels: str) -> None:
        val = max(0.0, float(value))
        key = tuple(str(labels.get(ln, "")) for ln in self.label_names)
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1
            self._sums[key] = self._sums.get(key, 0.0) + val

            if key not in self._bucket_counts:
                self._bucket_counts[key] = [0] * len(self.buckets)

            for i, bound in enumerate(self.buckets):
                if val <= bound:
                    self._bucket_counts[key][i] += 1

    def render(self) -> List[str]:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            for key in sorted(self._counts.keys()):
                base_labels = dict(zip(self.label_names, key)) if self.label_names else {}
                count = self._counts[key]
                total_sum = self._sums[key]
                b_counts = self._bucket_counts[key]

                for i, bound in enumerate(self.buckets):
                    lbl = dict(base_labels)
                    lbl["le"] = str(bound)
                    lines.append(f"{self.name}_bucket{_format_labels(lbl)} {b_counts[i]}")

                # +Inf bucket
                lbl_inf = dict(base_labels)
                lbl_inf["le"] = "+Inf"
                lines.append(f"{self.name}_bucket{_format_labels(lbl_inf)} {count}")

                lines.append(f"{self.name}_count{_format_labels(base_labels)} {count}")
                lines.append(f"{self.name}_sum{_format_labels(base_labels)} {total_sum:.6f}")
        return lines


class MetricsRegistry:
    """
    Centralized, thread-safe Prometheus Metrics Registry for Tech News Scrapper.
    """

    def __init__(self) -> None:
        self._start_time = time.time()
        self._lock = threading.Lock()

        # Uptime
        self.uptime_gauge = Gauge("technews_uptime_seconds", "Process uptime in seconds")

        # HTTP & API Metrics
        self.http_requests_total = Counter(
            "technews_http_requests_total",
            "Total HTTP requests received",
            label_names=["method", "endpoint", "status_code"],
        )
        self.http_request_duration_seconds = Histogram(
            "technews_http_request_duration_seconds",
            "HTTP request latency in seconds",
            label_names=["method", "endpoint"],
        )
        self.rate_limit_throttled_total = Counter(
            "technews_rate_limit_throttled_total",
            "Total HTTP requests throttled by rate limiter",
            label_names=["role"],
        )

        # Acquisition & Swarm Metrics
        self.zombie_acquisitions_total = Counter(
            "technews_zombie_acquisitions_total",
            "Total zombie acquisition attempts",
            label_names=["species", "status"],
        )
        self.zombie_hunt_duration_seconds = Histogram(
            "technews_zombie_hunt_duration_seconds",
            "Zombie collection execution latency",
            label_names=["species"],
        )
        self.ssrf_blocked_total = Counter(
            "technews_ssrf_blocked_total",
            "Total outbound requests blocked by SSRFGuard",
            label_names=["target_category"],
        )

        # Ingestion Queue Metrics
        self.queue_depth = Gauge("technews_queue_depth", "Current count of items in priority ingestion queue")
        self.queue_items_enqueued_total = Counter(
            "technews_queue_items_enqueued_total",
            "Total observations enqueued into priority queue",
            label_names=["priority"],
        )
        self.queue_items_dropped_total = Counter(
            "technews_queue_items_dropped_total",
            "Total observations dropped by priority queue",
            label_names=["reason"],
        )
        self.queue_backpressure_active = Gauge(
            "technews_queue_backpressure_active",
            "1 if queue backpressure is currently triggered, 0 otherwise",
        )
        self.queue_avg_wait_seconds = Gauge(
            "technews_queue_avg_wait_seconds",
            "Rolling average wait time for popped queue items",
        )

        # Canonical Pipeline S01-S11 Metrics
        self.pipeline_runs_total = Counter(
            "technews_pipeline_runs_total",
            "Total executions of CanonicalPipelineRunner",
            label_names=["status"],
        )
        self.pipeline_stage_duration_seconds = Histogram(
            "technews_pipeline_stage_duration_seconds",
            "Execution duration per pipeline stage S01 through S11",
            label_names=["stage"],
        )
        self.pipeline_stage_failures_total = Counter(
            "technews_pipeline_stage_failures_total",
            "Total stage-level processing failures",
            label_names=["stage", "reason"],
        )
        self.pipeline_articles_persisted_total = Counter(
            "technews_pipeline_articles_persisted_total",
            "Total normalized articles written to canonical storage",
        )
        self.pipeline_events_updated_total = Counter(
            "technews_pipeline_events_updated_total",
            "Total canonical events created or updated by pipeline",
        )

        # Storage & Diagnostic Gauges
        self.db_articles_total = Gauge(
            "technews_db_articles_total",
            "Total canonical articles stored in SQLite database",
        )
        self.db_events_total = Gauge(
            "technews_db_events_total",
            "Total canonical tech events stored in SQLite database",
        )

    def render_prometheus(self) -> str:
        """Render all registered metrics in standard Prometheus exposition format."""
        self.uptime_gauge.set(time.time() - self._start_time)
        output_blocks: List[str] = []

        collectors = [
            self.uptime_gauge,
            self.http_requests_total,
            self.http_request_duration_seconds,
            self.rate_limit_throttled_total,
            self.zombie_acquisitions_total,
            self.zombie_hunt_duration_seconds,
            self.ssrf_blocked_total,
            self.queue_depth,
            self.queue_items_enqueued_total,
            self.queue_items_dropped_total,
            self.queue_backpressure_active,
            self.queue_avg_wait_seconds,
            self.pipeline_runs_total,
            self.pipeline_stage_duration_seconds,
            self.pipeline_stage_failures_total,
            self.pipeline_articles_persisted_total,
            self.pipeline_events_updated_total,
            self.db_articles_total,
            self.db_events_total,
        ]

        for c in collectors:
            lines = c.render()
            if lines:
                output_blocks.append("\n".join(lines))

        return "\n\n".join(output_blocks) + "\n"


# Global shared metrics singleton
_global_metrics: Optional[MetricsRegistry] = None
_metrics_lock = threading.Lock()


def get_metrics_registry() -> MetricsRegistry:
    """Retrieve global shared MetricsRegistry singleton."""
    global _global_metrics
    if _global_metrics is None:
        with _metrics_lock:
            if _global_metrics is None:
                _global_metrics = MetricsRegistry()
    return _global_metrics
