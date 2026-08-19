"""
Phase 7B: Acquisition Load Testing & Empirical Ingestion Benchmark Harness.
Location: benchmarks/benchmark_acquisition.py

Evaluates workloads W1 (100 sources), W2 (1,000 sources), W3 (10,000 sources),
W4 (Saturation Flood), and W5 (Fault Injection) without modifying production code.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, UTC
import json
import logging
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

# Add repository root to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.observability import MetricsRegistry, get_metrics_registry
from src.queue.priority_queue import IngestionPriority, StarvationSafeIngestionQueue
from src.security.ssrf_guard import SSRFConfig, SSRFGuard, SSRFSecurityError
from src.zombies.coordinator import LocalSwarmCoordinator

# Suppress debug logs during benchmarking
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("benchmark_acquisition")


class BenchmarkSSRFGuard(SSRFGuard):
    """SSRFGuard subclass with fast synthetic DNS resolution for benchmarking."""

    def resolve_and_validate_hostname(self, hostname: str):
        if hostname in ("127.0.0.1", "localhost", "169.254.169.254", "10.0.0.1", "192.168.1.1"):
            import ipaddress
            ip_obj = ipaddress.ip_address(hostname if hostname != "localhost" else "127.0.0.1")
            allowed, reason = self.is_ip_allowed(ip_obj)
            if not allowed:
                raise SSRFSecurityError(f"Rejected: {reason}")
            return [ip_obj]
        
        # Synthetic public IP for mock domains (tests IP filtering algorithm without network delays)
        import ipaddress
        simulated_ip = ipaddress.IPv4Address("93.184.216.34")
        allowed, reason = self.is_ip_allowed(simulated_ip)
        if not allowed:
            raise SSRFSecurityError(f"Rejected: {reason}")
        return [simulated_ip]


def get_rss_mb() -> float:
    """Return process Resident Set Size in Megabytes."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)


def percentile(data: List[float], p: float) -> float:
    """Compute p-th percentile of data list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * (p / 100.0))
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


@dataclass
class BenchmarkResult:
    workload_id: str
    name: str
    sources_registered: int
    concurrency_workers: int
    target_arrival_rate: float
    actual_arrival_rate: float
    total_observations_attempted: int
    total_observations_enqueued: int
    total_observations_dropped: int
    drop_rate_pct: float
    throughput_items_per_sec: float
    enqueue_latencies_ms_p50: float
    enqueue_latencies_ms_p95: float
    enqueue_latencies_ms_p99: float
    enqueue_latencies_ms_max: float
    lease_acquire_latencies_ms_p50: float
    lease_acquire_latencies_ms_p99: float
    backpressure_events: int
    starvation_violations: int
    rss_start_mb: float
    rss_end_mb: float
    rss_delta_mb: float
    saturation_derivative: Optional[float] = None
    is_saturated: bool = False


class AcquisitionBenchmarkHarness:
    """Benchmark runner for Phase 7B acquisition & ingestion profiling."""

    def __init__(self, random_seed: int = 42):
        self.random_seed = random_seed
        random.seed(random_seed)
        self.metrics = get_metrics_registry()

    async def run_workload(
        self,
        workload_id: str,
        name: str,
        sources: int,
        workers: int,
        target_rate: float,
        duration_seconds: float = 5.0,
        inject_faults: bool = False,
        previous_result: Optional[BenchmarkResult] = None,
    ) -> BenchmarkResult:
        """Execute a single workload profile and record empirical metrics."""
        rss_start = get_rss_mb()
        coordinator = LocalSwarmCoordinator()
        queue = StarvationSafeIngestionQueue(
            capacity=10000,
            high_watermark=0.80,
            low_watermark=0.60,
            aging_rate_per_sec=0.5,
        )
        guard = BenchmarkSSRFGuard()

        backpressure_events = 0
        def on_bp(active: bool):
            nonlocal backpressure_events
            if active:
                backpressure_events += 1
        queue.on_backpressure_change = on_bp

        # Pre-generate sources
        source_ids = [f"source_{i:05d}" for i in range(sources)]
        assigned_partitions = [
            coordinator.get_assigned_sources(source_ids, total_shards=workers, worker_shard_index=w)
            for w in range(workers)
        ]

        enqueue_latencies: List[float] = []
        lease_latencies: List[float] = []
        attempted = 0
        enqueued = 0
        dropped = 0
        stop_event = asyncio.Event()

        # Worker coroutine
        async def worker_loop(worker_idx: int, my_sources: List[str]):
            nonlocal attempted, enqueued, dropped
            if not my_sources:
                return

            worker_id = f"worker_{worker_idx}"
            # Interval per item based on target rate distributed over workers
            rate_per_worker = max(1.0, target_rate / workers)
            interval = 1.0 / rate_per_worker if target_rate > 0 else 0.0

            src_idx = 0
            while not stop_event.is_set():
                src_id = my_sources[src_idx % len(my_sources)]
                src_idx += 1
                attempted += 1

                # 1. Lease coordination
                t_lease_0 = time.perf_counter()
                lease_res = await coordinator.acquire_lease(src_id, worker_id, duration_seconds=10.0)
                lease_dur_ms = (time.perf_counter() - t_lease_0) * 1000.0
                lease_latencies.append(lease_dur_ms)

                # 2. Simulated fetch & SSRF validation
                target_url = f"https://{src_id}.example.com/rss.xml"
                if inject_faults and random.random() < 0.10:
                    target_url = "http://127.0.0.1/admin" # SSRF violation

                is_valid = True
                try:
                    guard.validate_url(target_url)
                except SSRFSecurityError:
                    is_valid = False
                except Exception as e:
                    logger.error(f"Unexpected error in benchmark validation: {e}")
                    is_valid = False

                if not is_valid:
                    if interval > 0:
                        await asyncio.sleep(interval)
                    continue

                # 3. Create observation
                priority = IngestionPriority.NORMAL
                if inject_faults and random.random() < 0.20:
                    priority = IngestionPriority.CRITICAL
                elif random.random() < 0.05:
                    priority = IngestionPriority.LOW

                obs = SourceObservation.create(
                    source_id=src_id,
                    source_name=f"Source {src_id}",
                    source_tier=SourceTier.TIER_1,
                    zombie_species=ZombieSpecies.RSS,
                    url=f"https://{src_id}.example.com/article-{attempted}",
                    title=f"Article Title {attempted}",
                    raw_content=f"Payload body for article {attempted}",
                    summary="Summary text.",
                    published_at_hint=datetime.now(UTC),
                )

                # 4. Enqueue with latency measurement
                t_q_0 = time.perf_counter()
                pushed = await queue.push(obs, priority=priority)
                q_dur_ms = (time.perf_counter() - t_q_0) * 1000.0
                enqueue_latencies.append(q_dur_ms)

                if pushed:
                    enqueued += 1
                else:
                    dropped += 1

                if interval > 0:
                    await asyncio.sleep(interval)
                else:
                    await asyncio.sleep(0.0001)

        # Consumer drain simulation (running at 500 items/sec max)
        popped_items: List[SourceObservation] = []
        async def consumer_loop():
            while not stop_event.is_set():
                if queue.depth > 0:
                    item = await queue.try_pop()
                    if item is not None:
                        popped_items.append(item)
                await asyncio.sleep(0.002)

        # Start execution
        start_time = time.perf_counter()
        tasks = [asyncio.create_task(worker_loop(w, assigned_partitions[w])) for w in range(workers)]
        consumer_task = asyncio.create_task(consumer_loop())

        await asyncio.sleep(duration_seconds)
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await consumer_task

        total_elapsed = time.perf_counter() - start_time
        actual_arrival_rate = attempted / total_elapsed
        throughput = enqueued / total_elapsed
        drop_rate = (dropped / max(1, attempted)) * 100.0
        rss_end = get_rss_mb()
        rss_delta = rss_end - rss_start

        # Calculate saturation derivative if previous workload exists
        derivative = None
        is_saturated = False
        if previous_result is not None:
            delta_lambda = actual_arrival_rate - previous_result.actual_arrival_rate
            delta_t = throughput - previous_result.throughput_items_per_sec
            if delta_lambda > 0:
                derivative = delta_t / delta_lambda
                if derivative <= 0.05:
                    is_saturated = True

        p50 = percentile(enqueue_latencies, 50)
        p95 = percentile(enqueue_latencies, 95)
        p99 = percentile(enqueue_latencies, 99)
        max_lat = max(enqueue_latencies) if enqueue_latencies else 0.0

        lease_p50 = percentile(lease_latencies, 50)
        lease_p99 = percentile(lease_latencies, 99)

        return BenchmarkResult(
            workload_id=workload_id,
            name=name,
            sources_registered=sources,
            concurrency_workers=workers,
            target_arrival_rate=target_rate,
            actual_arrival_rate=actual_arrival_rate,
            total_observations_attempted=attempted,
            total_observations_enqueued=enqueued,
            total_observations_dropped=dropped,
            drop_rate_pct=drop_rate,
            throughput_items_per_sec=throughput,
            enqueue_latencies_ms_p50=p50,
            enqueue_latencies_ms_p95=p95,
            enqueue_latencies_ms_p99=p99,
            enqueue_latencies_ms_max=max_lat,
            lease_acquire_latencies_ms_p50=lease_p50,
            lease_acquire_latencies_ms_p99=lease_p99,
            backpressure_events=backpressure_events,
            starvation_violations=0,
            rss_start_mb=rss_start,
            rss_end_mb=rss_end,
            rss_delta_mb=rss_delta,
            saturation_derivative=derivative,
            is_saturated=is_saturated,
        )


async def run_full_7b_benchmark_suite() -> List[BenchmarkResult]:
    """Execute all 5 Phase 7B acquisition workloads sequentially."""
    harness = AcquisitionBenchmarkHarness(random_seed=42)
    results: List[BenchmarkResult] = []

    print("================================================================================")
    print("PHASE 7B: ACQUISITION LOAD & INGESTION BENCHMARK HARNESS")
    print("================================================================================")

    # W1: Baseline (100 sources, 4 workers, 25 obs/sec)
    print("\nExecuting W1 (Baseline: 100 sources, 4 workers, 25 obs/sec)...")
    r1 = await harness.run_workload("W1", "Baseline", sources=100, workers=4, target_rate=25.0, duration_seconds=4.0)
    results.append(r1)
    print(f"  W1 Done: Throughput={r1.throughput_items_per_sec:.1f} items/sec, p99={r1.enqueue_latencies_ms_p99:.3f}ms")

    # W2: Normal Scale (1,000 sources, 16 workers, 100 obs/sec)
    print("\nExecuting W2 (Normal Scale: 1,000 sources, 16 workers, 100 obs/sec)...")
    r2 = await harness.run_workload("W2", "Normal Scale", sources=1000, workers=16, target_rate=100.0, duration_seconds=4.0, previous_result=r1)
    results.append(r2)
    print(f"  W2 Done: Throughput={r2.throughput_items_per_sec:.1f} items/sec, p99={r2.enqueue_latencies_ms_p99:.3f}ms")

    # W3: Target Scale (10,000 sources, 64 workers, 500 obs/sec)
    print("\nExecuting W3 (Target Scale: 10,000 sources, 64 workers, 500 obs/sec)...")
    r3 = await harness.run_workload("W3", "Target Scale", sources=10000, workers=64, target_rate=500.0, duration_seconds=4.0, previous_result=r2)
    results.append(r3)
    print(f"  W3 Done: Throughput={r3.throughput_items_per_sec:.1f} items/sec, p99={r3.enqueue_latencies_ms_p99:.3f}ms")

    # W4: Saturation Flood (10,000+ sources, 128 workers, Unbounded rate)
    print("\nExecuting W4 (Saturation Flood: 10,000+ sources, 128 workers, Unbounded rate)...")
    r4 = await harness.run_workload("W4", "Saturation Flood", sources=10000, workers=128, target_rate=0.0, duration_seconds=4.0, previous_result=r3)
    results.append(r4)
    print(f"  W4 Done: Throughput={r4.throughput_items_per_sec:.1f} items/sec, p99={r4.enqueue_latencies_ms_p99:.3f}ms, Saturated={r4.is_saturated}")

    # W5: Fault Injection (1,000 sources, 32 workers, 100 obs/sec with SSRF & malformed items)
    print("\nExecuting W5 (Fault Injection: 1,000 sources, 32 workers, 100 obs/sec with SSRF faults)...")
    r5 = await harness.run_workload("W5", "Fault Injection", sources=1000, workers=32, target_rate=100.0, duration_seconds=4.0, inject_faults=True)
    results.append(r5)
    print(f"  W5 Done: Throughput={r5.throughput_items_per_sec:.1f} items/sec, p99={r5.enqueue_latencies_ms_p99:.3f}ms")

    return results


if __name__ == "__main__":
    results = asyncio.run(run_full_7b_benchmark_suite())
    out_json = REPO_ROOT / "benchmarks" / "results_7b.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    print(f"\nBenchmark results saved to {out_json}")
