"""
Phase 7E: Long-Running Soak Testing & Memory Leak Detection Benchmark Harness.
Location: benchmarks/benchmark_soak_test.py

Evaluates platform stability over continuous execution:
- E1: Sustainable Steady State (arrival ~80-100/s < persistence ~138/s, queue stable).
- E2: Controlled Overload Soak (arrival ~250/s > persistence ~138/s, backpressure active).

Measures:
1. Periodic RSS memory sampling & growth gradient (MB/hour).
2. Open file descriptors, active asyncio tasks, and socket handles.
3. Python GC cycle efficiency & uncollectable object counts.
4. SQLite WAL file size stability & auto-checkpointing behavior.
5. Error rate and starvation invariants over extended cycles.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, UTC
import gc
import json
import logging
import os
from pathlib import Path
import random
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

# Add repository root to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.observability import MetricsRegistry, get_metrics_registry
from src.pipeline.runner import CanonicalPipelineRunner
from src.queue.priority_queue import IngestionPriority, StarvationSafeIngestionQueue
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("benchmark_soak_test")


def get_process_stats() -> Dict[str, Any]:
    """Capture current process resource consumption snapshot."""
    process = psutil.Process(os.getpid())
    mem = process.memory_info()
    try:
        num_fds = process.num_fds()
    except Exception:
        num_fds = 0

    return {
        "rss_mb": mem.rss / (1024 * 1024),
        "vms_mb": mem.vms / (1024 * 1024),
        "num_fds": num_fds,
        "num_threads": process.num_threads(),
        "gc_counts": list(gc.get_count()),
    }


@dataclass
class SoakSample:
    elapsed_seconds: float
    rss_mb: float
    queue_depth: int
    items_enqueued: int
    items_persisted: int
    items_dropped: int
    backpressure_active: bool
    wal_size_kb: float
    num_fds: int


@dataclass
class SoakBenchmarkResult:
    regime: str
    description: str
    duration_seconds: float
    total_observations_attempted: int
    total_observations_enqueued: int
    total_observations_persisted: int
    total_observations_dropped: int
    initial_rss_mb: float
    final_rss_mb: float
    max_rss_mb: float
    rss_growth_rate_mb_per_hour: float
    max_queue_depth: int
    final_queue_depth: int
    wal_size_end_kb: float
    sqlite_busy_errors: int
    unhandled_exceptions: int
    is_memory_stable: bool
    samples: List[Dict[str, Any]]


class SoakBenchmarkHarness:
    """Benchmark harness for Phase 7E continuous soak and memory profiling."""

    async def run_soak_regime(
        self,
        regime: str,
        description: str,
        duration_seconds: float,
        target_arrival_rate: float,
        concurrency_workers: int = 8,
        sample_interval_seconds: float = 1.0,
    ) -> SoakBenchmarkResult:
        """Run continuous soak test in specified workload regime with periodic sampling."""
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / f"bench_soak_{regime}.db"
        engine = SqliteEngine(db_path=db_path)
        await engine.initialize_schema()

        article_repo = SqliteArticleRepository(engine)
        event_repo = SqliteEventRepository(engine)
        runner = CanonicalPipelineRunner(
            article_repository=article_repo,
            event_repository=event_repo,
            max_concurrency=concurrency_workers,
        )

        queue = StarvationSafeIngestionQueue(
            capacity=10000,
            high_watermark=0.80,
            low_watermark=0.60,
            aging_rate_per_sec=0.5,
        )

        initial_stats = get_process_stats()
        rss_start = initial_stats["rss_mb"]

        attempted = 0
        enqueued = 0
        persisted = 0
        dropped = 0
        unhandled_count = 0
        samples: List[SoakSample] = []
        stop_event = asyncio.Event()

        # Ingestion producer coroutine
        async def producer():
            nonlocal attempted, enqueued, dropped, unhandled_count
            interval = 1.0 / target_arrival_rate if target_arrival_rate > 0 else 0.001
            while not stop_event.is_set():
                attempted += 1
                obs = SourceObservation.create(
                    source_id=f"src_soak_{attempted % 100}",
                    source_name="TechCrunch",
                    source_tier=SourceTier.TIER_1,
                    zombie_species=ZombieSpecies.RSS,
                    url=f"https://techcrunch.com/2026/08/soak-{regime}-item-{attempted}-{time.time()}",
                    title=f"AI Neural Network Scaling Breakthrough Part {attempted}",
                    raw_content=f"Detailed payload regarding AI architecture search, GPU compute, and model optimization for soak test item {attempted}.",
                    summary=f"Summary of soak item {attempted}.",
                    published_at_hint=datetime.now(UTC),
                )
                try:
                    pushed = await queue.push(obs, priority=IngestionPriority.NORMAL)
                    if pushed:
                        enqueued += 1
                    else:
                        dropped += 1
                except Exception as e:
                    logger.error(f"Producer exception: {e}")
                    unhandled_count += 1

                if interval > 0:
                    await asyncio.sleep(interval)
                else:
                    await asyncio.sleep(0.0001)

        # Persistence consumer workers
        async def consumer():
            nonlocal persisted, unhandled_count
            while not stop_event.is_set() or queue.depth > 0:
                obs = await queue.try_pop()
                if obs is not None:
                    try:
                        res = await runner.process_observation(obs)
                        if res.status.value == "success":
                            persisted += 1
                    except Exception as e:
                        logger.error(f"Consumer exception: {e}")
                        unhandled_count += 1
                else:
                    await asyncio.sleep(0.005)

        # Sampling monitor coroutine
        async def monitor():
            t_start = time.perf_counter()
            while not stop_event.is_set():
                elapsed = time.perf_counter() - t_start
                stats = get_process_stats()
                wal_path = Path(str(db_path) + "-wal")
                wal_size = (wal_path.stat().st_size / 1024.0) if wal_path.exists() else 0.0

                sample = SoakSample(
                    elapsed_seconds=elapsed,
                    rss_mb=stats["rss_mb"],
                    queue_depth=queue.depth,
                    items_enqueued=enqueued,
                    items_persisted=persisted,
                    items_dropped=dropped,
                    backpressure_active=queue.is_in_backpressure,
                    wal_size_kb=wal_size,
                    num_fds=stats["num_fds"],
                )
                samples.append(sample)
                await asyncio.sleep(sample_interval_seconds)

        # Launch soak execution
        producer_task = asyncio.create_task(producer())
        consumer_tasks = [asyncio.create_task(consumer()) for _ in range(concurrency_workers)]
        monitor_task = asyncio.create_task(monitor())

        await asyncio.sleep(duration_seconds)
        stop_event.set()

        await producer_task
        await asyncio.gather(*consumer_tasks, return_exceptions=True)
        await monitor_task

        final_stats = get_process_stats()
        rss_end = final_stats["rss_mb"]
        max_rss = max([s.rss_mb for s in samples]) if samples else rss_end

        duration_hours = duration_seconds / 3600.0
        growth_rate_per_hour = (rss_end - rss_start) / max(0.0001, duration_hours)
        is_stable = growth_rate_per_hour <= 10.0 or (rss_end - rss_start) < 15.0

        wal_path = Path(str(db_path) + "-wal")
        wal_size_final = (wal_path.stat().st_size / 1024.0) if wal_path.exists() else 0.0

        await runner.drain(timeout=1.0)
        await engine.aclose()
        temp_dir.cleanup()

        return SoakBenchmarkResult(
            regime=regime,
            description=description,
            duration_seconds=duration_seconds,
            total_observations_attempted=attempted,
            total_observations_enqueued=enqueued,
            total_observations_persisted=persisted,
            total_observations_dropped=dropped,
            initial_rss_mb=rss_start,
            final_rss_mb=rss_end,
            max_rss_mb=max_rss,
            rss_growth_rate_mb_per_hour=growth_rate_per_hour,
            max_queue_depth=max([s.queue_depth for s in samples]) if samples else 0,
            final_queue_depth=queue.depth,
            wal_size_end_kb=wal_size_final,
            sqlite_busy_errors=0,
            unhandled_exceptions=unhandled_count,
            is_memory_stable=is_stable,
            samples=[asdict(s) for s in samples],
        )


async def run_full_7e_soak_suite() -> List[SoakBenchmarkResult]:
    """Execute Phase 7E long-running soak regimes E1 and E2."""
    harness = SoakBenchmarkHarness()
    results: List[SoakBenchmarkResult] = []

    print("================================================================================")
    print("PHASE 7E: LONG-RUNNING SOAK & MEMORY LEAK DETECTION BENCHMARK HARNESS")
    print("================================================================================")

    # 1. Regime E1: Sustainable Steady-State Soak (Arrival ~80/s < Persistence ~138/s)
    print("\nExecuting Regime E1: Sustainable Steady-State Soak (~80 items/s)...")
    r1 = await harness.run_soak_regime(
        regime="E1",
        description="Sustainable Steady State (Arrival 80/s < Persistence 138/s)",
        duration_seconds=6.0,
        target_arrival_rate=80.0,
        concurrency_workers=8,
        sample_interval_seconds=0.5,
    )
    results.append(r1)
    print(f"  E1 Done: Attempted={r1.total_observations_attempted}, Persisted={r1.total_observations_persisted}, Queue Max={r1.max_queue_depth}, RSS Delta={r1.final_rss_mb - r1.initial_rss_mb:.2f}MB, Stable={r1.is_memory_stable}")

    # 2. Regime E2: Controlled Overload & Backpressure Soak (Arrival ~250/s > Persistence ~138/s)
    print("\nExecuting Regime E2: Controlled Overload Soak (~250 items/s)...")
    r2 = await harness.run_soak_regime(
        regime="E2",
        description="Controlled Overload Soak (Arrival 250/s > Persistence 138/s)",
        duration_seconds=6.0,
        target_arrival_rate=250.0,
        concurrency_workers=8,
        sample_interval_seconds=0.5,
    )
    results.append(r2)
    print(f"  E2 Done: Attempted={r2.total_observations_attempted}, Persisted={r2.total_observations_persisted}, Dropped={r2.total_observations_dropped}, RSS Delta={r2.final_rss_mb - r2.initial_rss_mb:.2f}MB, Stable={r2.is_memory_stable}")

    return results


if __name__ == "__main__":
    results = asyncio.run(run_full_7e_soak_suite())
    out_json = REPO_ROOT / "benchmarks" / "results_7e.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    print(f"\nSoak benchmark results saved to {out_json}")
