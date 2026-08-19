"""
Structured JSON Production Logging & Trace Context Integration.
Location: src/observability/logging.py
"""

from __future__ import annotations

from datetime import datetime, UTC
import json
import logging
from typing import Any, Dict

from .tracing import Tracer


class StructuredJsonFormatter(logging.Formatter):
    """
    JSON Log Formatter for cloud log aggregators (ELK, CloudWatch, Datadog).
    
    Automatically enriches log entries with active OpenTelemetry trace_id and span_id.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Inject active trace context if available
        span_ctx = Tracer.get_current_context()
        if span_ctx:
            log_entry["trace_id"] = span_ctx.trace_id
            log_entry["span_id"] = span_ctx.span_id

        # Attach custom extra fields passed to logger
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if hasattr(record, "source_id"):
            log_entry["source_id"] = record.source_id
        if hasattr(record, "stage"):
            log_entry["stage"] = record.stage
        if hasattr(record, "reason"):
            log_entry["reason"] = record.reason

        # Exception information if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def configure_structured_logging(level: int = logging.INFO) -> None:
    """Configure root logger with StructuredJsonFormatter."""
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    root.addHandler(handler)
