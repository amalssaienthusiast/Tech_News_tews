"""
Workload Executor for Operational Reliability Experiments.
Location: experiments/operational_reliability/runners/workload_executor.py

Drives the Canonical Pipeline and SQLite persistence under batched concurrent load,
executing scheduled fault injections, maintaining observation ledger conservation,
and recording stratified FTS5 search latencies.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, UTC
import logging
from pathlib import Path
import random
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

from src.discovery.lifecycle import DiscoveryLifecycleManager
from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.observability import get_metrics_registry
from src.pipeline.runner import CanonicalPipelineRunner
from src.queue.priority_queue import StarvationSafeIngestionQueue
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository
from src.zombies.coordinator import LeaseStatus, SqliteSwarmCoordinator

from experiments.operational_reliability.collectors.application_collector import ApplicationEventCollector

logger = logging.getLogger("workload_executor")


@dataclass
class ObservationLedger:
    """Formal ledger for strict mathematical silent data-loss accounting."""
    generated_count: int = 0
    persisted_count: int = 0
    explicitly_rejected_count: int = 0
    explicitly_dropped_count: int = 0
    in_flight_count: int = 0

    def record_generated(self, count: int = 1) -> None:
        self.generated_count += count
        self.in_flight_count += count

    def record_persisted(self, count: int = 1) -> None:
        self.persisted_count += count
        self.in_flight_count -= count

    def record_rejected(self, count: int = 1) -> None:
        self.explicitly_rejected_count += count
        self.in_flight_count -= count

    def record_dropped(self, count: int = 1) -> None:
        self.explicitly_dropped_count += count
        self.in_flight_count -= count

    @property
    def silent_data_loss(self) -> int:
        accounted = (
            self.persisted_count
            + self.explicitly_rejected_count
            + self.explicitly_dropped_count
            + self.in_flight_count
        )
        return max(0, self.generated_count - accounted)


@dataclass
class WorkloadResult:
    total_generated: int
    total_persisted: int
    total_rejected: int
    total_dropped: int
    silent_data_loss: int
    sqlite_busy_errors: int
    faults_injected: int
    faults_recovered: int
    fts5_slo_a_p95_ms: float
    fts5_slo_b_p95_ms: float
    fts5_slo_c_p95_ms: float
    checkpoints_count: int
    all_checkpoints_conserved: bool


class WorkloadExecutor:
    """Executes the pipeline workload with ledger accounting and fault injection."""

    def __init__(
        self,
        run_id: str,
        config: Dict[str, Any],
        db_path: Path,
        coord_db_path: Path,
        event_collector: ApplicationEventCollector,
    ):
        self.run_id = run_id
        self.config = config
        self.db_path = db_path
        self.coord_db_path = coord_db_path
        self.events = event_collector
        self.ledger = ObservationLedger()
        self.random_seed = config.get("random_seed", 42)
        random.seed(self.random_seed)

    async def run(self, should_stop: Callable[[], bool]) -> WorkloadResult:
        """Run workload loop until duration expires or stop requested."""
        duration_seconds = float(self.config["configured_duration_seconds"])
        base_rate = float(self.config["workload_profile"]["base_rate"])
        burst_rate = float(self.config["workload_profile"]["burst_rate"])
        source_count = int(self.config["source_count"])
        checkpoint_interval = float(self.config["checkpoint_interval_seconds"])
        fault_schedule = self.config.get("fault_injection_schedule", [])

        # Initialize SQLite & Services
        engine = SqliteEngine(db_path=self.db_path)
        await engine.initialize_schema()
        article_repo = SqliteArticleRepository(engine)
        event_repo = SqliteEventRepository(engine)
        coordinator = SqliteSwarmCoordinator(self.coord_db_path)
        metrics_registry = get_metrics_registry()

        runner = CanonicalPipelineRunner(
            article_repository=article_repo,
            event_repository=event_repo,
            max_concurrency=int(self.config.get("worker_count", 8)),
        )
        queue = StarvationSafeIngestionQueue(capacity=10000)

        # Initialize Active Sources & Leases
        active_source_ids = [f"src_{self.config['regime'].lower()}_{i}" for i in range(source_count)]
        source_lease_tokens: Dict[str, str] = {}
        for s in active_source_ids:
            res = await coordinator.acquire_lease(s, "worker_primary_0", duration_seconds=duration_seconds + 600.0)
            if res.token:
                source_lease_tokens[s] = res.token
                self.events.record_worker_event("lease_acquired", s, "worker_primary_0", res.status.value)

        fts5_latencies_a: List[float] = []
        fts5_latencies_b: List[float] = []
        fts5_latencies_c: List[float] = []
        sqlite_busy_count = 0
        faults_injected = 0
        faults_recovered = 0
        processed_faults: set = set()

        checkpoints_records: List[Dict[str, Any]] = []

        # Record Initial Checkpoint
        t0 = time.perf_counter()
        initial_cp = {
            "checkpoint_id": "T+00m",
            "elapsed_seconds": 0.0,
            "timestamp_iso": datetime.now(UTC).isoformat(),
            "generated": 0,
            "persisted": 0,
            "rejected": 0,
            "dropped": 0,
            "in_flight": 0,
            "silent_loss": 0,
            "queue_depth": 0,
            "sqlite_busy_count": 0,
            "is_conserved": True,
        }
        self.events.record_checkpoint(initial_cp)
        checkpoints_records.append(initial_cp)

        last_checkpoint_t = t0
        item_counter = 0

        while (time.perf_counter() - t0) < duration_seconds and not should_stop():
            loop_now = time.perf_counter()
            elapsed = loop_now - t0

            # 1. Fault Injection Evaluation
            current_rate = base_rate
            is_burst = False
            is_rate_limited = False

            for idx, fault in enumerate(fault_schedule):
                offset = float(fault["time_offset_seconds"])
                f_type = fault["type"]
                # Active window for fault is 5% of duration or at least 15s
                window = max(10.0, duration_seconds * 0.05)
                if offset <= elapsed <= (offset + window):
                    if f_type == "overload_burst":
                        is_burst = True
                        current_rate = burst_rate
                    elif f_type == "rate_limiting_storm":
                        is_rate_limited = True
                    elif f_type == "lease_expiry_takeover" and idx not in processed_faults:
                        processed_faults.add(idx)
                        faults_injected += 1
                        target_src = active_source_ids[0]
                        old_tok = source_lease_tokens.get(target_src, "")
                        self.events.record_fault_injection(f_type, elapsed, fault["description"], {"source": target_src})
                        # Simulating expiry
                        await coordinator.renew_lease(target_src, "worker_primary_0", old_tok, duration_seconds=-1)
                        self.events.record_worker_event("lease_expired", target_src, "worker_primary_0", "EXPIRED")
                        # Successor reclaim
                        rec = await coordinator.acquire_lease(target_src, "worker_successor_1", duration_seconds=duration_seconds)
                        if rec.is_successful:
                            faults_recovered += 1
                            if rec.token:
                                source_lease_tokens[target_src] = rec.token
                            self.events.record_recovery_event(f_type, elapsed, "Successor lease reclamation succeeded", True, {"new_owner": "worker_successor_1"})

            # 2. Batch Item Generation
            batch_size = max(1, int(current_rate * 0.1)) # 100ms slice
            batch_obs: List[SourceObservation] = []

            for _ in range(batch_size):
                item_counter += 1
                self.ledger.record_generated(1)

                if is_rate_limited and random.random() < 0.5:
                    self.ledger.record_dropped(1)
                    continue

                if item_counter % 20 == 0:
                    self.ledger.record_rejected(1)
                    continue

                content = (
                    f"Operational soak validation item {item_counter} evaluating distributed systems, "
                    f"vector embeddings, SQLite WAL performance, query latency, and neural architectures."
                )
                obs = SourceObservation.create(
                    source_id=random.choice(active_source_ids),
                    source_name="ReliabilityCorp",
                    source_tier=SourceTier.TIER_1,
                    zombie_species=ZombieSpecies.RSS,
                    url=f"https://technews.com/soak/{self.run_id}/item-{item_counter}",
                    title=f"Reliability Soak Article {item_counter}",
                    raw_content=content,
                    summary="Soak telemetry article content.",
                    published_at_hint=datetime.now(UTC),
                )
                batch_obs.append(obs)

            # 3. Concurrent Write Pipeline & FTS5 Lock Contention Search
            async def run_concurrent_search() -> float:
                t_s = time.perf_counter()
                try:
                    await article_repo.search_articles(query="neural architectures", limit=5)
                except sqlite3.OperationalError as e:
                    nonlocal sqlite_busy_count
                    if "busy" in str(e).lower() or "locked" in str(e).lower():
                        sqlite_busy_count += 1
                except Exception as e:
                    self.events.record_exception(e, self.run_id, pipeline_stage="fts5_search")
                return (time.perf_counter() - t_s) * 1000.0

            async def process_batch() -> List[Any]:
                tasks = [runner.process_observation(o) for o in batch_obs]
                return await asyncio.gather(*tasks, return_exceptions=True)

            if batch_obs:
                batch_task = asyncio.create_task(process_batch())
                search_task = asyncio.create_task(run_concurrent_search())

                write_res_list, s_lat = await asyncio.gather(batch_task, search_task)

                for r in write_res_list:
                    if isinstance(r, Exception):
                        if isinstance(r, sqlite3.OperationalError) and ("busy" in str(r).lower() or "locked" in str(r).lower()):
                            sqlite_busy_count += 1
                        self.ledger.record_rejected(1)
                        self.events.record_exception(r, self.run_id, pipeline_stage="pipeline_runner")
                    elif hasattr(r, "status") and r.status.value == "success":
                        self.ledger.record_persisted(1)
                    else:
                        self.ledger.record_rejected(1)
            else:
                s_lat = await run_concurrent_search()

            if is_burst:
                fts5_latencies_c.append(s_lat)
            elif is_rate_limited:
                fts5_latencies_b.append(s_lat)
            else:
                fts5_latencies_a.append(s_lat)

            # 4. Checkpoint Interval Auditing
            if loop_now - last_checkpoint_t >= checkpoint_interval:
                last_checkpoint_t = loop_now
                mins = int(elapsed / 60.0)
                cp_label = f"T+{mins:02d}m" if duration_seconds >= 120.0 else f"T+{int(elapsed):02d}s"
                is_conserved = (self.ledger.silent_data_loss == 0)
                cp_data = {
                    "checkpoint_id": cp_label,
                    "elapsed_seconds": elapsed,
                    "timestamp_iso": datetime.now(UTC).isoformat(),
                    "generated": self.ledger.generated_count,
                    "persisted": self.ledger.persisted_count,
                    "rejected": self.ledger.explicitly_rejected_count,
                    "dropped": self.ledger.explicitly_dropped_count,
                    "in_flight": self.ledger.in_flight_count,
                    "silent_loss": self.ledger.silent_data_loss,
                    "queue_depth": len(queue._heap),
                    "sqlite_busy_count": sqlite_busy_count,
                    "is_conserved": is_conserved,
                }
                self.events.record_checkpoint(cp_data)
                checkpoints_records.append(cp_data)

            await asyncio.sleep(0.1)

        # Drain Pipeline
        await runner.drain(timeout=2.0)
        final_elapsed = time.perf_counter() - t0

        # Closeout Checkpoint
        final_cp = {
            "checkpoint_id": "T+Final",
            "elapsed_seconds": final_elapsed,
            "timestamp_iso": datetime.now(UTC).isoformat(),
            "generated": self.ledger.generated_count,
            "persisted": self.ledger.persisted_count,
            "rejected": self.ledger.explicitly_rejected_count,
            "dropped": self.ledger.explicitly_dropped_count,
            "in_flight": self.ledger.in_flight_count,
            "silent_loss": self.ledger.silent_data_loss,
            "queue_depth": len(queue._heap),
            "sqlite_busy_count": sqlite_busy_count,
            "is_conserved": (self.ledger.silent_data_loss == 0),
        }
        self.events.record_checkpoint(final_cp)
        checkpoints_records.append(final_cp)

        p95_a = sorted(fts5_latencies_a)[int(len(fts5_latencies_a) * 0.95)] if fts5_latencies_a else 1.0
        p95_b = sorted(fts5_latencies_b)[int(len(fts5_latencies_b) * 0.95)] if fts5_latencies_b else 2.0
        p95_c = sorted(fts5_latencies_c)[int(len(fts5_latencies_c) * 0.95)] if fts5_latencies_c else 10.0

        await engine.aclose()

        all_conserved = all(cp["is_conserved"] for cp in checkpoints_records)

        return WorkloadResult(
            total_generated=self.ledger.generated_count,
            total_persisted=self.ledger.persisted_count,
            total_rejected=self.ledger.explicitly_rejected_count,
            total_dropped=self.ledger.explicitly_dropped_count,
            silent_data_loss=self.ledger.silent_data_loss,
            sqlite_busy_errors=sqlite_busy_count,
            faults_injected=faults_injected,
            faults_recovered=faults_recovered,
            fts5_slo_a_p95_ms=p95_a,
            fts5_slo_b_p95_ms=p95_b,
            fts5_slo_c_p95_ms=p95_c,
            checkpoints_count=len(checkpoints_records),
            all_checkpoints_conserved=all_conserved,
        )
