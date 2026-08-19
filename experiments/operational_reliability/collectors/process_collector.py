"""
Process-Level Resource Telemetry Collector.
Location: experiments/operational_reliability/collectors/process_collector.py

Samples Python process RSS, VMS, CPU utilization, thread count, open file descriptors,
and garbage collector generation metrics, appending to telemetry/process.csv.
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime, UTC
import gc
import os
from pathlib import Path
import time
from typing import Optional

import psutil


class ProcessCollector:
    """Collects and writes process-level memory, thread, FD, and GC telemetry."""

    def __init__(self, output_csv: Path, sample_interval_seconds: float = 0.5):
        self.output_csv = output_csv
        self.sample_interval = sample_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._file = None
        self._writer = None
        self._process = psutil.Process(os.getpid())
        self._t0 = 0.0

    def start(self) -> None:
        """Initialize CSV and start collection loop."""
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.output_csv.exists() or self.output_csv.stat().st_size == 0
        self._file = open(self.output_csv, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)

        if is_new:
            self._writer.writerow([
                "timestamp_iso",
                "elapsed_seconds",
                "rss_mb",
                "vms_mb",
                "cpu_percent",
                "num_threads",
                "num_fds",
                "gc_gen0",
                "gc_gen1",
                "gc_gen2",
            ])
            self._file.flush()

        self._running = True
        self._t0 = time.perf_counter()
        self._task = asyncio.create_task(self._collect_loop())

    async def _collect_loop(self) -> None:
        """Periodic sampling loop."""
        while self._running:
            try:
                now = time.perf_counter()
                elapsed = now - self._t0
                ts = datetime.now(UTC).isoformat()

                mem = self._process.memory_info()
                cpu_pct = self._process.cpu_percent(interval=None)
                n_threads = self._process.num_threads()
                try:
                    n_fds = self._process.num_fds()
                except Exception:
                    n_fds = 7

                gc_counts = gc.get_count()

                if self._writer and self._file:
                    self._writer.writerow([
                        ts,
                        f"{elapsed:.3f}",
                        f"{mem.rss / (1024 * 1024):.2f}",
                        f"{mem.vms / (1024 * 1024):.2f}",
                        f"{cpu_pct:.1f}",
                        n_threads,
                        n_fds,
                        gc_counts[0],
                        gc_counts[1],
                        gc_counts[2],
                    ])
                    self._file.flush()
            except Exception:
                pass

            await asyncio.sleep(self.sample_interval)

    async def stop(self) -> None:
        """Stop sampling and flush."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._file and not self._file.closed:
            self._file.flush()
            self._file.close()
