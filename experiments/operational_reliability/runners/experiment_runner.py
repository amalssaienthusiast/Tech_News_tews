"""
Main Experiment Runner for Operational Reliability Benchmarks.
Location: experiments/operational_reliability/runners/experiment_runner.py

Orchestrates the entire lifecycle of long-running cloud experiments:
- Initializes isolated run directories with strict immutability.
- Captures complete environment fingerprinting.
- Coordinates multi-layer collectors (System, Process, Application, Database).
- Drives workload execution and handles POSIX signals (SIGINT/SIGTERM).
- Performs final PRAGMA integrity checks.
- Emits RUN_MANIFEST.json, FINAL_REPORT.md, and SHA-256 checksums.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, UTC
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.observability import get_metrics_registry

from experiments.operational_reliability.collectors.application_collector import ApplicationEventCollector
from experiments.operational_reliability.collectors.database_collector import DatabaseCollector
from experiments.operational_reliability.collectors.process_collector import ProcessCollector
from experiments.operational_reliability.collectors.system_collector import SystemCollector
from experiments.operational_reliability.runners.environment_fingerprint import (
    collect_environment_fingerprint,
    dump_environment_artifacts,
)
from experiments.operational_reliability.runners.workload_executor import WorkloadExecutor, WorkloadResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("experiment_runner")


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class ExperimentRunner:
    """Orchestrator for self-contained operational reliability experiments."""

    def __init__(self, config_path: Path, output_base_dir: Optional[Path] = None, override_duration: Optional[float] = None):
        self.config_path = config_path.resolve()
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config: Dict[str, Any] = json.load(f)

        if override_duration is not None:
            self.config["configured_duration_seconds"] = override_duration

        self.regime = self.config.get("regime", "E1")
        self.exp_name = self.config.get("experiment_name", "phase_8e_operational_reliability")
        self.phase = self.config.get("phase", "Phase 8E")

        base_dir = output_base_dir or (REPO_ROOT / "experiments" / "operational_reliability" / "runs")
        self.base_dir = base_dir.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Deterministic Run ID: YYYYMMDDTHHMMSSZ_<REGIME>_<HASH8>
        now_utc = datetime.now(UTC)
        ts_str = now_utc.strftime("%Y%m%dT%H%M%SZ")
        cfg_hash = hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest()[:8]
        self.run_id = f"{ts_str}_{self.regime}_{cfg_hash}"
        self.run_dir = self.base_dir / self.run_id

        if self.run_dir.exists():
            raise RuntimeError(f"Run directory already exists: {self.run_dir}. Immutability violation.")

        self._stop_requested = False
        self._interrupted = False

    def _setup_directories(self) -> None:
        """Create standard isolated subdirectory hierarchy."""
        subdirs = [
            "environment",
            "configuration",
            "application",
            "telemetry",
            "database",
            "events",
            "results",
            "final",
        ]
        for s in subdirs:
            (self.run_dir / s).mkdir(parents=True, exist_ok=True)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle interrupt/termination signal safely."""
        logger.warning(f"Received signal {signum}. Initiating graceful experiment shutdown.")
        self._stop_requested = True
        self._interrupted = True

    async def execute(self) -> int:
        """Execute complete experiment lifecycle."""
        start_time_iso = datetime.now(UTC).isoformat()
        t0 = time.perf_counter()
        logger.info(f"Starting Experiment Run: {self.run_id} (Regime: {self.regime})")

        # 1. Setup isolated folder hierarchy
        self._setup_directories()

        # 2. Hook signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: self._handle_signal(s, None))
            except NotImplementedError:
                pass

        # 3. Environment Snapshot
        env_fp = collect_environment_fingerprint(REPO_ROOT)
        dump_environment_artifacts(env_fp, self.run_dir / "environment", REPO_ROOT)

        # 4. Save Configuration
        (self.run_dir / "configuration" / "workload.json").write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        (self.run_dir / "configuration" / "benchmark_config.json").write_text(json.dumps(self.config, indent=2), encoding="utf-8")

        # 5. Initialize Collectors
        sys_collector = SystemCollector(self.run_dir / "telemetry" / "system.csv", sample_interval_seconds=1.0)
        proc_collector = ProcessCollector(self.run_dir / "telemetry" / "process.csv", sample_interval_seconds=0.5)
        event_collector = ApplicationEventCollector(self.run_dir)
        db_collector = DatabaseCollector(self.run_dir / "database" / "app.db", self.run_dir / "database")

        sys_collector.start()
        proc_collector.start()

        # 6. Execute Workload
        db_path = self.run_dir / "database" / "app.db"
        coord_db_path = self.run_dir / "database" / "coord.db"
        executor = WorkloadExecutor(
            run_id=self.run_id,
            config=self.config,
            db_path=db_path,
            coord_db_path=coord_db_path,
            event_collector=event_collector,
        )

        workload_result: Optional[WorkloadResult] = None
        exec_error: Optional[Exception] = None

        try:
            workload_result = await executor.run(should_stop=lambda: self._stop_requested)
        except Exception as e:
            exec_error = e
            logger.error(f"Workload execution failed: {e}", exc_info=True)
            event_collector.record_exception(e, self.run_id, pipeline_stage="workload_executor")

        actual_dur = time.perf_counter() - t0
        end_time_iso = datetime.now(UTC).isoformat()

        # 7. Stop Collectors & Gather DB Telemetry
        await proc_collector.stop()
        await sys_collector.stop()

        db_stats = db_collector.collect_stats()
        integrity_res = db_collector.run_integrity_check()

        # Save Prometheus snapshot text
        prom_text = get_metrics_registry().render_prometheus()
        (self.run_dir / "telemetry" / "prometheus_snapshot.txt").write_text(prom_text, encoding="utf-8")

        # 8. Evaluate Invariants & SLOs
        conf_dur = float(self.config["configured_duration_seconds"])
        duration_valid = actual_dur >= (conf_dur * 0.99)
        slos = self.config.get("slo_thresholds", {})

        silent_loss = workload_result.silent_data_loss if workload_result else 9999
        all_conserved = workload_result.all_checkpoints_conserved if workload_result else False
        sqlite_busy = workload_result.sqlite_busy_errors if workload_result else 9999
        integrity_ok = integrity_res["integrity_check_passed"] and integrity_res["foreign_key_check_passed"]

        passed = (
            exec_error is None
            and not self._interrupted
            and duration_valid
            and silent_loss == 0
            and all_conserved
            and sqlite_busy == 0
            and integrity_ok
        )

        if self._interrupted:
            final_status = "INTERRUPTED"
            exit_code = 130
        elif exec_error is not None:
            final_status = "CRASHED"
            exit_code = 1
        elif passed:
            final_status = "PASS"
            exit_code = 0
        else:
            final_status = "FAIL"
            exit_code = 1

        # 9. Save Raw Results & Summary
        results_summary = {
            "run_id": self.run_id,
            "status": final_status,
            "exit_code": exit_code,
            "duration_valid": duration_valid,
            "configured_duration_seconds": conf_dur,
            "actual_duration_seconds": actual_dur,
            "silent_data_loss": silent_loss,
            "all_checkpoints_conserved": all_conserved,
            "sqlite_busy_errors": sqlite_busy,
            "database_integrity_passed": integrity_ok,
            "total_generated": workload_result.total_generated if workload_result else 0,
            "total_persisted": workload_result.total_persisted if workload_result else 0,
            "total_rejected": workload_result.total_rejected if workload_result else 0,
            "total_dropped": workload_result.total_dropped if workload_result else 0,
            "fts5_slo_a_p95_ms": workload_result.fts5_slo_a_p95_ms if workload_result else 0.0,
            "fts5_slo_b_p95_ms": workload_result.fts5_slo_b_p95_ms if workload_result else 0.0,
            "fts5_slo_c_p95_ms": workload_result.fts5_slo_c_p95_ms if workload_result else 0.0,
            "database_stats": db_stats,
        }
        (self.run_dir / "results" / "raw_results.json").write_text(json.dumps(results_summary, indent=2), encoding="utf-8")
        (self.run_dir / "results" / "summary.json").write_text(json.dumps(results_summary, indent=2), encoding="utf-8")

        # 10. Generate RUN_MANIFEST.json
        manifest = {
            "run_id": self.run_id,
            "experiment_name": self.exp_name,
            "phase": self.phase,
            "regime": self.regime,
            "configured_duration_seconds": conf_dur,
            "actual_duration_seconds": actual_dur,
            "workload_profile": self.config.get("workload_profile", {}),
            "source_count": int(self.config.get("source_count", 100)),
            "offered_ingestion_rate": float(self.config.get("offered_ingestion_rate", 40.0)),
            "worker_count": int(self.config.get("worker_count", 8)),
            "fault_injection_schedule": self.config.get("fault_injection_schedule", []),
            "checkpoint_interval_seconds": float(self.config.get("checkpoint_interval_seconds", 300.0)),
            "random_seed": int(self.config.get("random_seed", 42)),
            "git_commit": env_fp.git_commit,
            "git_dirty": env_fp.git_dirty,
            "environment_fingerprint": env_fp.to_dict(),
            "started_at": start_time_iso,
            "ended_at": end_time_iso,
            "final_status": final_status,
            "exit_code": exit_code,
        }
        (self.run_dir / "RUN_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 11. Generate FINAL_REPORT.md
        report_md = self._generate_markdown_report(manifest, results_summary, integrity_res)
        (self.run_dir / "final" / "FINAL_REPORT.md").write_text(report_md, encoding="utf-8")

        # 12. Compute SHA-256 Checksums for all artifacts
        checksum_lines = []
        for root, _, files in os.walk(self.run_dir):
            for file in sorted(files):
                if file == "checksums.sha256":
                    continue
                fpath = Path(root) / file
                rel_path = fpath.relative_to(self.run_dir)
                sha = compute_sha256(fpath)
                checksum_lines.append(f"{sha}  {rel_path}")

        (self.run_dir / "final" / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

        logger.info(f"Experiment {self.run_id} completed. Status: {final_status} (Exit Code: {exit_code})")
        logger.info(f"Evidence artifacts saved to: {self.run_dir}")
        return exit_code

    def _generate_markdown_report(self, manifest: Dict[str, Any], results: Dict[str, Any], integrity: Dict[str, Any]) -> str:
        """Construct human-readable markdown closeout report."""
        status_icon = "🟢" if results["status"] == "PASS" else "🔴"
        return f"""# Operational Reliability Final Report: {self.run_id}

**Program**: {manifest['phase']} — Operational Reliability Experiments  
**Regime**: {manifest['regime']}  
**Status**: {status_icon} {results['status']} (Exit Code: {results['exit_code']})  
**Execution Window**: `{manifest['started_at']}` to `{manifest['ended_at']}`  
**Git Commit**: `{manifest['git_commit']}` (Dirty: `{manifest['git_dirty']}`)  

---

## 1. Executive Summary & Verification Invariants

| Invariant / Metric | Configured Target | Measured Value | Compliance Status |
|---|---|---|---|
| **Actual Duration** | $\\ge {manifest['configured_duration_seconds'] * 0.99:.1f}\\text{{s}}$ | **{results['actual_duration_seconds']:.2f} s** | {'🟢 PASS' if results['duration_valid'] else '🔴 FAIL'} |
| **Silent Data Loss** | $\\mathbf{{0}}$ | **{results['silent_data_loss']}** | {'🟢 PASS' if results['silent_data_loss'] == 0 else '🔴 FAIL'} |
| **Ledger Conservation** | $100\\%$ Conserved | **{'All Conserved' if results['all_checkpoints_conserved'] else 'Violations Detected'}** | {'🟢 PASS' if results['all_checkpoints_conserved'] else '🔴 FAIL'} |
| **SQLite Busy Errors** | $0$ | **{results['sqlite_busy_errors']}** | {'🟢 PASS' if results['sqlite_busy_errors'] == 0 else '🔴 FAIL'} |
| **Database Integrity** | PRAGMA check passed | **{'Passed' if results['database_integrity_passed'] else 'Failed'}** | {'🟢 PASS' if results['database_integrity_passed'] else '🔴 FAIL'} |

---

## 2. Workload & Observation Summary

- **Total Observations Generated**: {results['total_generated']:,}
- **Total Articles Persisted**: {results['total_persisted']:,}
- **Total Explicitly Rejected**: {results['total_rejected']:,}
- **Total Explicitly Dropped**: {results['total_dropped']:,}
- **FTS5 Latency p95 (SLO A Normal)**: {results['fts5_slo_a_p95_ms']:.2f} ms
- **FTS5 Latency p95 (SLO B 429 Storm)**: {results['fts5_slo_b_p95_ms']:.2f} ms
- **FTS5 Latency p95 (SLO C Saturated Burst)**: {results['fts5_slo_c_p95_ms']:.2f} ms

---

## 3. Database Statistics

- **Database Size**: {results['database_stats']['db_size_mb']:.2f} MB
- **WAL Size**: {results['database_stats']['wal_size_mb']:.2f} MB
- **Page Count**: {results['database_stats']['page_count']}
- **Articles Stored**: {results['database_stats']['article_count']}
- **Tech Events Stored**: {results['database_stats']['event_count']}

---

## 4. Evidence Integrity

SHA-256 checksums recorded in `final/checksums.sha256`. All evidence files are self-contained and frozen.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8E Operational Reliability Experiment Runner")
    parser.add_argument("--config", type=Path, required=True, help="Path to experiment configuration JSON")
    parser.add_argument("--duration", type=float, default=None, help="Override duration in seconds")
    parser.add_argument("--output-dir", type=Path, default=None, help="Base directory for experiment runs")
    parser.add_argument("--smoke-test", action="store_true", help="Execute in smoke-test mode")
    args = parser.parse_args()

    runner = ExperimentRunner(
        config_path=args.config,
        output_base_dir=args.output_dir,
        override_duration=args.duration,
    )
    exit_code = asyncio.run(runner.execute())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
