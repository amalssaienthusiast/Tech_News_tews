"""
System-Level Resource Telemetry Collector.
Location: experiments/operational_reliability/collectors/system_collector.py

Periodically samples host-level CPU, load averages, memory, swap, disk I/O,
and network traffic, appending time-series records to telemetry/system.csv.
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime, UTC
import os
from pathlib import Path
import time
from typing import Optional

import psutil


class SystemCollector:
    """Collects and writes OS-level hardware and resource telemetry."""

    def __init__(self, output_csv: Path, sample_interval_seconds: float = 1.0):
        self.output_csv = output_csv
        self.sample_interval = sample_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._file = None
        self._writer = None
        self._t0 = 0.0

    def start(self) -> None:
        """Initialize the CSV output file with standard headers and start collection loop."""
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.output_csv.exists() or self.output_csv.stat().st_size == 0
        self._file = open(self.output_csv, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)

        if is_new:
            self._writer.writerow([
                "timestamp_iso",
                "elapsed_seconds",
                "cpu_percent",
                "load_1m",
                "load_5m",
                "load_15m",
                "ram_used_mb",
                "ram_free_mb",
                "ram_percent",
                "swap_used_mb",
                "disk_used_gb",
                "disk_free_gb",
                "disk_read_bytes",
                "disk_write_bytes",
                "net_rx_bytes",
                "net_tx_bytes",
            ])
            self._file.flush()

        self._running = True
        self._t0 = time.perf_counter()
        self._task = asyncio.create_task(self._collect_loop())

    async def _collect_loop(self) -> None:
        """Periodic background collection loop."""
        while self._running:
            try:
                now = time.perf_counter()
                elapsed = now - self._t0
                ts = datetime.now(UTC).isoformat()

                cpu_pct = psutil.cpu_percent(interval=None)
                try:
                    load1, load5, load15 = psutil.getloadavg()
                except Exception:
                    load1, load5, load15 = 0.0, 0.0, 0.0

                vmem = psutil.virtual_memory()
                swap = psutil.swap_memory()
                disk = psutil.disk_usage(os.getcwd())

                try:
                    dio = psutil.disk_io_counters()
                    disk_read_bytes = dio.read_bytes if dio else 0
                    disk_write_bytes = dio.write_bytes if dio else 0
                except Exception:
                    disk_read_bytes, disk_write_bytes = 0, 0

                try:
                    nio = psutil.net_io_counters()
                    net_rx_bytes = nio.bytes_recv if nio else 0
                    net_tx_bytes = nio.bytes_sent if nio else 0
                except Exception:
                    net_rx_bytes, net_tx_bytes = 0, 0

                if self._writer and self._file:
                    self._writer.writerow([
                        ts,
                        f"{elapsed:.3f}",
                        f"{cpu_pct:.1f}",
                        f"{load1:.2f}",
                        f"{load5:.2f}",
                        f"{load15:.2f}",
                        f"{vmem.used / (1024 * 1024):.2f}",
                        f"{vmem.free / (1024 * 1024):.2f}",
                        f"{vmem.percent:.1f}",
                        f"{swap.used / (1024 * 1024):.2f}",
                        f"{disk.used / (1024 * 1024 * 1024):.2f}",
                        f"{disk.free / (1024 * 1024 * 1024):.2f}",
                        disk_read_bytes,
                        disk_write_bytes,
                        net_rx_bytes,
                        net_tx_bytes,
                    ])
                    self._file.flush()
            except Exception:
                pass

            await asyncio.sleep(self.sample_interval)

    async def stop(self) -> None:
        """Stop sampling and close file descriptor."""
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
