"""
OpenTelemetry Tracing & Context Propagation Bridge.
Location: src/observability/tracing.py

Provides async context propagation across Zombie -> Ingestion Queue -> Pipeline S01-S11 -> Storage:
- Lean trace context correlation bridge (trace_id, span_id, worker_id)
- ContextVar-based async context propagation
- Zero schema or dataclass mutations to frozen Phase 5 domain entities
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import secrets
import time
from typing import Any, AsyncIterator, Dict, Mapping, Optional

# Context variable tracking current active span
_current_span_ctx: ContextVar[Optional[SpanContext]] = ContextVar("current_span_ctx", default=None)


def generate_trace_id() -> str:
    """Generate 128-bit hexadecimal trace ID."""
    return secrets.token_hex(16)


def generate_span_id() -> str:
    """Generate 64-bit hexadecimal span ID."""
    return secrets.token_hex(8)


@dataclass(frozen=True, slots=True)
class SpanContext:
    """Immutable trace and span correlation context."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    operation_name: str = ""
    start_timestamp: float = field(default_factory=time.time)

    def to_correlation_metadata(self, worker_id: Optional[str] = None) -> Dict[str, str]:
        """
        Produce a lean correlation dictionary for SourceObservation.metadata.
        Carries ONLY essential correlation IDs, strictly avoiding bloated diagnostic payloads.
        """
        meta: Dict[str, str] = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }
        if worker_id:
            meta["worker_id"] = worker_id
        return meta

    @classmethod
    def from_metadata(
        cls,
        metadata: Optional[Mapping[str, Any]],
        operation_name: str = "pipeline_execution",
    ) -> Optional[SpanContext]:
        """Reconstruct a parent SpanContext from correlation metadata dictionary if present."""
        if not metadata:
            return None
        trace_id = metadata.get("trace_id")
        span_id = metadata.get("span_id")
        if trace_id and span_id:
            return cls(
                trace_id=str(trace_id),
                span_id=str(span_id),
                operation_name=operation_name,
            )
        return None


class Tracer:
    """Asynchronous Tracer managing span lifecycles and context propagation."""

    @staticmethod
    def get_current_context() -> Optional[SpanContext]:
        """Retrieve the active SpanContext from contextvars."""
        return _current_span_ctx.get()

    @staticmethod
    def start_trace(operation_name: str, worker_id: Optional[str] = None) -> SpanContext:
        """Start a new root trace context."""
        ctx = SpanContext(
            trace_id=generate_trace_id(),
            span_id=generate_span_id(),
            parent_span_id=None,
            operation_name=operation_name,
        )
        _current_span_ctx.set(ctx)
        return ctx

    @staticmethod
    @asynccontextmanager
    async def start_span(
        operation_name: str,
        parent_context: Optional[SpanContext] = None,
    ) -> AsyncIterator[SpanContext]:
        """
        Start a scoped child span, propagating contextvars for the duration of the async block.
        """
        parent = parent_context or _current_span_ctx.get()
        trace_id = parent.trace_id if parent else generate_trace_id()
        parent_span_id = parent.span_id if parent else None
        span_id = generate_span_id()

        child_ctx = SpanContext(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
        )

        token = _current_span_ctx.set(child_ctx)
        try:
            yield child_ctx
        finally:
            _current_span_ctx.reset(token)
