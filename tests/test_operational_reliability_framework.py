"""
Unit & Integration Tests for the Phase 8E Operational Reliability Experimental Framework.
Location: tests/test_operational_reliability_framework.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import json
from pathlib import Path
import tempfile
import unittest

import pytest

from experiments.operational_reliability.analysis.run_analyzer import RunAnalyzer
from experiments.operational_reliability.collectors.application_collector import ApplicationEventCollector
from experiments.operational_reliability.collectors.database_collector import DatabaseCollector
from experiments.operational_reliability.collectors.process_collector import ProcessCollector
from experiments.operational_reliability.collectors.system_collector import SystemCollector
from experiments.operational_reliability.runners.environment_fingerprint import (
    collect_environment_fingerprint,
    dump_environment_artifacts,
)
from experiments.operational_reliability.runners.experiment_runner import ExperimentRunner

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestOperationalReliabilityFramework(unittest.TestCase):
    """Test suite verifying all components of the experimental framework."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_environment_fingerprint_collection(self):
        """Verify complete hardware, runtime, and Git environment capture."""
        fp = collect_environment_fingerprint(REPO_ROOT)
        self.assertTrue(len(fp.hostname) > 0)
        self.assertTrue(len(fp.platform) > 0)
        self.assertTrue(len(fp.python_version) > 0)
        self.assertTrue(len(fp.sqlite_version) > 0)
        self.assertTrue(fp.cpu_cores_logical >= 1)
        self.assertTrue(fp.ram_total_mb > 0)

        # Verify dump files
        env_dir = self.test_dir / "environment"
        dump_environment_artifacts(fp, env_dir, REPO_ROOT)

        expected_files = [
            "git.txt",
            "python.txt",
            "pip-freeze.txt",
            "os-release.txt",
            "kernel.txt",
            "cpu.txt",
            "memory.txt",
            "disk.txt",
            "sqlite.txt",
            "docker.txt",
        ]
        for f in expected_files:
            fpath = env_dir / f
            self.assertTrue(fpath.exists(), f"Missing environment dump file: {f}")
            self.assertTrue(fpath.stat().st_size > 0, f"Empty environment dump file: {f}")

    def test_multi_layer_collectors(self):
        """Verify System, Process, Application, and Database collectors."""
        async def _test():
            run_dir = self.test_dir / "collector_run"
            run_dir.mkdir(parents=True, exist_ok=True)

            sys_csv = run_dir / "telemetry" / "system.csv"
            proc_csv = run_dir / "telemetry" / "process.csv"

            sys_col = SystemCollector(sys_csv, sample_interval_seconds=0.1)
            proc_col = ProcessCollector(proc_csv, sample_interval_seconds=0.1)
            app_col = ApplicationEventCollector(run_dir)

            sys_col.start()
            proc_col.start()

            # Record sample application events
            app_col.record_checkpoint({"checkpoint_id": "T+00m", "generated": 10, "persisted": 10, "is_conserved": True})
            app_col.record_fault_injection("test_burst", 5.0, "Test burst fault")
            app_col.record_worker_event("acquire", "src_test", "worker_1", "ACQUIRED")
            app_col.record_recovery_event("test_burst", 6.0, "Recovered", True)
            app_col.record_log("INFO", "Test log message")

            await asyncio.sleep(0.35)

            await proc_col.stop()
            await sys_col.stop()

            self.assertTrue(sys_csv.exists())
            self.assertTrue(proc_csv.exists())
            self.assertTrue((run_dir / "events" / "checkpoints.jsonl").exists())
            self.assertTrue((run_dir / "events" / "fault_injections.jsonl").exists())
            self.assertTrue((run_dir / "events" / "worker_events.jsonl").exists())
            self.assertTrue((run_dir / "events" / "recovery_events.jsonl").exists())
            self.assertTrue((run_dir / "application" / "application.jsonl").exists())

            # Verify DatabaseCollector
            db_path = run_dir / "database" / "test.db"
            db_col = DatabaseCollector(db_path, run_dir / "database")
            stats = db_col.collect_stats()
            self.assertIn("db_size_bytes", stats)
            integrity = db_col.run_integrity_check()
            self.assertIn("integrity_check_passed", integrity)

        asyncio.run(_test())

    def test_smoke_experiment_lifecycle_and_offline_analysis(self):
        """Execute a short smoke experiment and run offline analysis against saved artifacts."""
        async def _test():
            config_path = REPO_ROOT / "experiments" / "operational_reliability" / "configs" / "smoke_test.json"
            runs_base = self.test_dir / "runs"

            runner = ExperimentRunner(
                config_path=config_path,
                output_base_dir=runs_base,
                override_duration=5.0,
            )
            exit_code = await runner.execute()
            self.assertEqual(exit_code, 0, "Experiment execution returned non-zero exit code")

            run_dir = runner.run_dir
            self.assertTrue(run_dir.exists())

            # Verify all required subdirectories exist
            for sub in ["environment", "configuration", "application", "telemetry", "database", "events", "results", "final"]:
                self.assertTrue((run_dir / sub).exists(), f"Missing subdirectory: {sub}")

            # Verify key artifact files exist
            self.assertTrue((run_dir / "RUN_MANIFEST.json").exists())
            self.assertTrue((run_dir / "configuration" / "workload.json").exists())
            self.assertTrue((run_dir / "telemetry" / "system.csv").exists())
            self.assertTrue((run_dir / "telemetry" / "process.csv").exists())
            self.assertTrue((run_dir / "telemetry" / "prometheus_snapshot.txt").exists())
            self.assertTrue((run_dir / "events" / "checkpoints.jsonl").exists())
            self.assertTrue((run_dir / "results" / "raw_results.json").exists())
            self.assertTrue((run_dir / "final" / "FINAL_REPORT.md").exists())
            self.assertTrue((run_dir / "final" / "checksums.sha256").exists())

            # Verify Offline Analysis against saved run directory
            analyzer = RunAnalyzer(run_dir)
            checksum_ok, mismatches = analyzer.verify_checksums()
            self.assertTrue(checksum_ok, f"Checksum verification failed: {mismatches}")

            eval_result = analyzer.evaluate_slos()
            self.assertIn("all_slos_passed", eval_result)
            self.assertTrue((run_dir / "results" / "slo_evaluation.json").exists())
            self.assertTrue((run_dir / "results" / "anomalies.json").exists())

            # Check conservation in analysis
            cp_audit = eval_result["checkpoint_audit"]
            self.assertTrue(cp_audit["all_conserved"])
            self.assertEqual(cp_audit["violations_count"], 0)

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
