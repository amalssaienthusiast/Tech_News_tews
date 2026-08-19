"""
Prometheus-Style Metrics Collector for Tech News Scraper.

Provides:
- Counter metrics (request totals, errors)
- Gauge metrics (queue sizes, active workers)
- Histogram metrics (latencies, durations)
- Custom metrics (LLM costs, article counts by source)

Metrics are exposed in Prometheus text format at /metrics endpoint.

Usage:
    from src.monitoring import get_metrics_collector
    
    metrics = get_metrics_collector()
    
    # Record a scrape
    metrics.record_scrape("techcrunch", success=True, duration_ms=1500)
    
    # Record bypass attempt
    metrics.record_bypass("medium", "stealth", success=True)
    
    # Get Prometheus format
    output = metrics.export_prometheus()
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from threading import Lock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# METRIC TYPES
# =============================================================================

@dataclass
class Counter:
    """A monotonically increasing counter metric."""
    name: str
    help: str
    labels: List[str] = field(default_factory=list)
    _values: Dict[tuple, float] = field(default_factory=lambda: defaultdict(float))
    _lock: Lock = field(default_factory=Lock)
    
    def inc(self, value: float = 1, **labels):
        """Increment counter by value."""
        key = tuple(labels.get(l, "") for l in self.labels)
        with self._lock:
            self._values[key] += value
    
    def get(self, **labels) -> float:
        """Get current counter value."""
        key = tuple(labels.get(l, "") for l in self.labels)
        return self._values.get(key, 0)
    
    def export(self) -> str:
        """Export to Prometheus format."""
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        for key, value in self._values.items():
            if self.labels:
                label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                lines.append(f"{self.name}{{{label_str}}} {value}")
            else:
                lines.append(f"{self.name} {value}")
        return "\n".join(lines)


@dataclass 
class Gauge:
    """A metric that can go up and down."""
    name: str
    help: str
    labels: List[str] = field(default_factory=list)
    _values: Dict[tuple, float] = field(default_factory=lambda: defaultdict(float))
    _lock: Lock = field(default_factory=Lock)
    
    def set(self, value: float, **labels):
        """Set gauge to value."""
        key = tuple(labels.get(l, "") for l in self.labels)
        with self._lock:
            self._values[key] = value
    
    def inc(self, value: float = 1, **labels):
        """Increment gauge."""
        key = tuple(labels.get(l, "") for l in self.labels)
        with self._lock:
            self._values[key] += value
    
    def dec(self, value: float = 1, **labels):
        """Decrement gauge."""
        key = tuple(labels.get(l, "") for l in self.labels)
        with self._lock:
            self._values[key] -= value
    
    def get(self, **labels) -> float:
        """Get current gauge value."""
        key = tuple(labels.get(l, "") for l in self.labels)
        return self._values.get(key, 0)
    
    def export(self) -> str:
        """Export to Prometheus format."""
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        for key, value in self._values.items():
            if self.labels:
                label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key))
                lines.append(f"{self.name}{{{label_str}}} {value}")
            else:
                lines.append(f"{self.name} {value}")
        return "\n".join(lines)


@dataclass
class Histogram:
    """A metric that samples observations into buckets."""
    name: str
    help: str
    labels: List[str] = field(default_factory=list)
    buckets: List[float] = field(default_factory=lambda: [0.1, 0.5, 1, 2, 5, 10, 30, 60])
    _counts: Dict[tuple, Dict[float, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    _sums: Dict[tuple, float] = field(default_factory=lambda: defaultdict(float))
    _totals: Dict[tuple, int] = field(default_factory=lambda: defaultdict(int))
    _lock: Lock = field(default_factory=Lock)
    
    def observe(self, value: float, **labels):
        """Record an observation."""
        key = tuple(labels.get(l, "") for l in self.labels)
        with self._lock:
            self._sums[key] += value
            self._totals[key] += 1
            for bucket in self.buckets:
                if value <= bucket:
                    self._counts[key][bucket] += 1
    
    def export(self) -> str:
        """Export to Prometheus format."""
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        
        for key in set(self._sums.keys()) | set(self._totals.keys()):
            label_str = ",".join(f'{l}="{v}"' for l, v in zip(self.labels, key)) if self.labels else ""
            base = f"{self.name}{{{label_str}" if label_str else f"{self.name}{{" 
            
            cumulative = 0
            for bucket in self.buckets:
                cumulative += self._counts.get(key, {}).get(bucket, 0)
                le_label = f'{label_str},le="{bucket}"' if label_str else f'le="{bucket}"'
                lines.append(f"{self.name}_bucket{{{le_label}}} {cumulative}")
            
            # +Inf bucket
            le_label = f'{label_str},le="+Inf"' if label_str else 'le="+Inf"'
            lines.append(f"{self.name}_bucket{{{le_label}}} {self._totals.get(key, 0)}")
            
            # Sum and count
            if label_str:
                lines.append(f"{self.name}_sum{{{label_str}}} {self._sums.get(key, 0)}")
                lines.append(f"{self.name}_count{{{label_str}}} {self._totals.get(key, 0)}")
            else:
                lines.append(f"{self.name}_sum {self._sums.get(key, 0)}")
                lines.append(f"{self.name}_count {self._totals.get(key, 0)}")
        
        return "\n".join(lines)


# =============================================================================
# METRICS COLLECTOR
# =============================================================================

class MetricsCollector:
    """
    Centralized metrics collection for Tech News Scraper.
    
    Collects Prometheus-compatible metrics for:
    - Scraping operations (success/failure by source)
    - Bypass technique effectiveness
    - LLM API usage and costs
    - Queue processing
    - Database operations
    """
    
    def __init__(self):
        """Initialize all metrics."""
        # Counter metrics
        self.scrape_requests = Counter(
            "technews_scrape_requests_total",
            "Total scrape requests by source and status",
            labels=["source", "status"]
        )
        
        self.bypass_attempts = Counter(
            "technews_bypass_attempts_total", 
            "Bypass attempts by platform, technique, and result",
            labels=["platform", "technique", "success"]
        )
        
        self.llm_requests = Counter(
            "technews_llm_requests_total",
            "LLM API requests by provider and model",
            labels=["provider", "model"]
        )
        
        self.llm_tokens = Counter(
            "technews_llm_tokens_total",
            "LLM tokens used by provider, model, and type",
            labels=["provider", "model", "type"]
        )
        
        self.llm_cost_usd = Counter(
            "technews_llm_cost_usd_total",
            "LLM API cost in USD by provider and model",
            labels=["provider", "model"]
        )
        
        self.articles_processed = Counter(
            "technews_articles_processed_total",
            "Total articles processed by source",
            labels=["source"]
        )
        
        self.errors = Counter(
            "technews_errors_total",
            "Total errors by component and type",
            labels=["component", "error_type"]
        )
        
        # Gauge metrics
        self.queue_depth = Gauge(
            "technews_queue_depth",
            "Current queue depth by queue name",
            labels=["queue"]
        )
        
        self.active_workers = Gauge(
            "technews_active_workers",
            "Currently active workers by type",
            labels=["worker_type"]
        )
        
        self.cache_size = Gauge(
            "technews_cache_size",
            "Current cache size in items",
            labels=["cache"]
        )
        
        # Histogram metrics
        self.scrape_duration = Histogram(
            "technews_scrape_duration_seconds",
            "Scrape duration in seconds by source",
            labels=["source"],
            buckets=[0.5, 1, 2, 5, 10, 30, 60, 120]
        )
        
        self.llm_latency = Histogram(
            "technews_llm_latency_seconds",
            "LLM API latency in seconds by provider",
            labels=["provider", "model"],
            buckets=[0.1, 0.5, 1, 2, 5, 10, 30]
        )
        
        self.db_query_duration = Histogram(
            "technews_db_query_duration_seconds",
            "Database query duration in seconds",
            labels=["operation"],
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1]
        )
        
        # Internal state
        self._start_time = datetime.now(UTC)
        
        logger.info("MetricsCollector initialized")
    
    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================
    
    def record_scrape(
        self,
        source: str,
        success: bool,
        duration_ms: float,
        articles_count: int = 0
    ):
        """Record a scrape operation."""
        status = "success" if success else "failure"
        self.scrape_requests.inc(source=source, status=status)
        self.scrape_duration.observe(duration_ms / 1000, source=source)
        
        if articles_count > 0:
            self.articles_processed.inc(articles_count, source=source)
    
    def record_bypass(
        self,
        platform: str,
        technique: str,
        success: bool,
        duration_ms: float = 0
    ):
        """Record a bypass attempt."""
        self.bypass_attempts.inc(
            platform=platform,
            technique=technique,
            success=str(success).lower()
        )
    
    def record_llm_request(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        cost_usd: float = 0
    ):
        """Record an LLM API request."""
        self.llm_requests.inc(provider=provider, model=model)
        self.llm_tokens.inc(input_tokens, provider=provider, model=model, type="input")
        self.llm_tokens.inc(output_tokens, provider=provider, model=model, type="output")
        self.llm_latency.observe(latency_ms / 1000, provider=provider, model=model)
        
        if cost_usd > 0:
            self.llm_cost_usd.inc(cost_usd, provider=provider, model=model)
    
    def record_db_operation(self, operation: str, duration_ms: float):
        """Record a database operation."""
        self.db_query_duration.observe(duration_ms / 1000, operation=operation)
    
    def record_error(self, component: str, error_type: str):
        """Record an error."""
        self.errors.inc(component=component, error_type=error_type)
    
    def set_queue_depth(self, queue: str, depth: int):
        """Set current queue depth."""
        self.queue_depth.set(depth, queue=queue)
    
    def set_active_workers(self, worker_type: str, count: int):
        """Set active worker count."""
        self.active_workers.set(count, worker_type=worker_type)
    
    # =========================================================================
    # EXPORT
    # =========================================================================
    
    def export_prometheus(self) -> str:
        """Export all metrics in Prometheus text format."""
        sections = []
        
        # Add uptime gauge
        uptime_seconds = (datetime.now(UTC) - self._start_time).total_seconds()
        sections.append(f"# HELP technews_uptime_seconds Application uptime in seconds")
        sections.append(f"# TYPE technews_uptime_seconds gauge")
        sections.append(f"technews_uptime_seconds {uptime_seconds:.2f}")
        sections.append("")
        
        # Export all metrics
        for metric in [
            self.scrape_requests,
            self.bypass_attempts,
            self.llm_requests,
            self.llm_tokens,
            self.llm_cost_usd,
            self.articles_processed,
            self.errors,
            self.queue_depth,
            self.active_workers,
            self.cache_size,
            self.scrape_duration,
            self.llm_latency,
            self.db_query_duration,
        ]:
            export = metric.export()
            if export:
                sections.append(export)
                sections.append("")
        
        return "\n".join(sections)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of key metrics."""
        return {
            "uptime_seconds": (datetime.now(UTC) - self._start_time).total_seconds(),
            "total_scrapes": sum(self.scrape_requests._values.values()),
            "total_errors": sum(self.errors._values.values()),
            "total_articles": sum(self.articles_processed._values.values()),
            "total_llm_requests": sum(self.llm_requests._values.values()),
            "total_llm_cost_usd": sum(self.llm_cost_usd._values.values()),
        }


# =============================================================================
# SINGLETON
# =============================================================================

_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get singleton MetricsCollector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector
