"""
Application Event and Failure Telemetry Collector.
Location: experiments/operational_reliability/collectors/application_collector.py

Streams append-only JSONL event records for conservation checkpoints, fault injections,
lease transitions, recoveries, structured logs, and detailed failure/exception reports.
"""

from __future__ import annotations

from datetime import datetime, UTC
import json
import os
from pathlib import Path
import traceback
from typing import Any, Dict, Optional

import psutil


class ApplicationEventCollector:
    """Manages append-only JSONL telemetry streams for application-level lifecycle and failure events."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.events_dir = run_dir / "events"
        self.app_dir = run_dir / "application"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.app_dir.mkdir(parents=True, exist_ok=True)

        self.checkpoints_file = self.events_dir / "checkpoints.jsonl"
        self.faults_file = self.events_dir / "fault_injections.jsonl"
        self.worker_events_file = self.events_dir / "worker_events.jsonl"
        self.recoveries_file = self.events_dir / "recovery_events.jsonl"
        self.exceptions_file = self.events_dir / "exceptions.jsonl"
        self.app_jsonl_file = self.app_dir / "application.jsonl"

    def record_checkpoint(self, checkpoint_data: Dict[str, Any]) -> None:
        """Append a conservation checkpoint record."""
        self._append_jsonl(self.checkpoints_file, checkpoint_data)

    def record_fault_injection(self, fault_type: str, time_offset_seconds: float, description: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Append a fault injection record."""
        record = {
            "timestamp_iso": datetime.now(UTC).isoformat(),
            "time_offset_seconds": time_offset_seconds,
            "fault_type": fault_type,
            "description": description,
            "details": details or {},
        }
        self._append_jsonl(self.faults_file, record)

    def record_worker_event(self, event_type: str, source_id: str, worker_id: str, status: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Append a coordinator lease or worker event."""
        record = {
            "timestamp_iso": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "source_id": source_id,
            "worker_id": worker_id,
            "status": status,
            "details": details or {},
        }
        self._append_jsonl(self.worker_events_file, record)

    def record_recovery_event(self, fault_type: str, time_offset_seconds: float, description: str, success: bool, details: Optional[Dict[str, Any]] = None) -> None:
        """Append a recovery event."""
        record = {
            "timestamp_iso": datetime.now(UTC).isoformat(),
            "time_offset_seconds": time_offset_seconds,
            "fault_type": fault_type,
            "description": description,
            "success": success,
            "details": details or {},
        }
        self._append_jsonl(self.recoveries_file, record)

    def record_exception(
        self,
        exc: Exception,
        run_id: str,
        pipeline_stage: Optional[str] = None,
        source_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        queue_depth: Optional[int] = None,
        db_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Capture and append full diagnostic context for an unexpected exception."""
        proc = psutil.Process(os.getpid())
        mem = proc.memory_info().rss / (1024 * 1024)
        try:
            fds = proc.num_fds()
        except Exception:
            fds = 7

        record = {
            "timestamp_iso": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "process_id": os.getpid(),
            "worker_id": worker_id or "unknown",
            "source_id": source_id or "unknown",
            "pipeline_stage": pipeline_stage or "unknown",
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "stack_trace": traceback.format_exc(),
            "rss_mb": round(mem, 2),
            "fd_count": fds,
            "queue_depth": queue_depth if queue_depth is not None else -1,
            "database_state": db_state or {},
        }
        self._append_jsonl(self.exceptions_file, record)

    def record_log(self, level: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Append a structured log record."""
        record = {
            "timestamp_iso": datetime.now(UTC).isoformat(),
            "level": level,
            "message": message,
            "context": context or {},
        }
        self._append_jsonl(self.app_jsonl_file, record)

    def _append_jsonl(self, file_path: Path, record: Dict[str, Any]) -> None:
        """Helper to append a single JSONLine with flush."""
        line = json.dumps(record) + "\n"
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
