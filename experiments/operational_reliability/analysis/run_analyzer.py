"""
Offline Run Analyzer for Operational Reliability Benchmarks.
Location: experiments/operational_reliability/analysis/run_analyzer.py

Consumes an immutable, self-contained experiment run directory from disk:
- Parses process and system CSV telemetry.
- Calculates memory statistical distribution and linear regression slope.
- Audits mathematical conservation across all JSONL checkpoint events.
- Evaluates SLO compliance and identifies anomalies.
- Operates 100% offline with zero external process, network, or live DB dependencies.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_analyzer")


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class RunAnalyzer:
    """Consumes and analyzes a completed experiment run directory offline."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir.resolve()
        if not self.run_dir.exists() or not self.run_dir.is_dir():
            raise FileNotFoundError(f"Run directory not found: {self.run_dir}")

        self.manifest_file = self.run_dir / "RUN_MANIFEST.json"
        if not self.manifest_file.exists():
            raise FileNotFoundError(f"RUN_MANIFEST.json not found in {self.run_dir}")

        with open(self.manifest_file, "r", encoding="utf-8") as f:
            self.manifest: Dict[str, Any] = json.load(f)

        self.config_file = self.run_dir / "configuration" / "workload.json"
        self.config: Dict[str, Any] = {}
        if self.config_file.exists():
            with open(self.config_file, "r", encoding="utf-8") as f:
                self.config = json.load(f)

    def verify_checksums(self) -> Tuple[bool, List[str]]:
        """Verify all files against final/checksums.sha256."""
        checksum_file = self.run_dir / "final" / "checksums.sha256"
        if not checksum_file.exists():
            return False, ["final/checksums.sha256 not found"]

        mismatches: List[str] = []
        with open(checksum_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "  " not in line:
                    continue
                expected_sha, rel_path = line.split("  ", 1)
                target_file = self.run_dir / rel_path
                if not target_file.exists():
                    mismatches.append(f"Missing file: {rel_path}")
                    continue
                actual_sha = compute_sha256(target_file)
                if actual_sha != expected_sha:
                    mismatches.append(f"Checksum mismatch for {rel_path} (expected {expected_sha}, got {actual_sha})")

        return len(mismatches) == 0, mismatches

    def analyze_process_telemetry(self) -> Dict[str, Any]:
        """Parse telemetry/process.csv for RSS distribution, regression slope, and FD stability."""
        csv_file = self.run_dir / "telemetry" / "process.csv"
        if not csv_file.exists():
            return {"error": "process.csv not found"}

        rss_vals: List[float] = []
        vms_vals: List[float] = []
        cpu_vals: List[float] = []
        fd_vals: List[int] = []
        elapsed_vals: List[float] = []

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    elapsed = float(row["elapsed_seconds"])
                    rss = float(row["rss_mb"])
                    vms = float(row["vms_mb"])
                    cpu = float(row["cpu_percent"])
                    fds = int(row["num_fds"])
                    elapsed_vals.append(elapsed)
                    rss_vals.append(rss)
                    vms_vals.append(vms)
                    cpu_vals.append(cpu)
                    fd_vals.append(fds)
                except Exception:
                    continue

        if not rss_vals:
            return {"error": "no valid samples in process.csv"}

        # Linear regression slope in MB/hr
        reg_slope = 0.0
        n = len(rss_vals)
        actual_dur = elapsed_vals[-1] if elapsed_vals else 0.0

        if actual_dur >= 60.0 and n >= 2:
            xs = [e / 3600.0 for e in elapsed_vals]
            ys = rss_vals
            sum_x = sum(xs)
            sum_y = sum(ys)
            sum_xx = sum(x * x for x in xs)
            sum_xy = sum(x * y for x, y in zip(xs, ys))
            denom = (n * sum_xx) - (sum_x * sum_x)
            if abs(denom) > 1e-9:
                reg_slope = max(0.0, ((n * sum_xy) - (sum_x * sum_y)) / denom)
        else:
            reg_slope = max(0.0, rss_vals[-1] - rss_vals[0])

        return {
            "sample_count": n,
            "rss_initial_mb": rss_vals[0],
            "rss_final_mb": rss_vals[-1],
            "rss_min_mb": min(rss_vals),
            "rss_max_mb": max(rss_vals),
            "rss_median_mb": sorted(rss_vals)[n // 2],
            "rss_net_delta_mb": round(rss_vals[-1] - rss_vals[0], 2),
            "rss_linear_regression_slope_mb_per_hr": round(reg_slope, 4),
            "fd_initial": fd_vals[0],
            "fd_final": fd_vals[-1],
            "fd_delta": fd_vals[-1] - fd_vals[0],
            "fd_max": max(fd_vals),
            "cpu_percent_mean": round(sum(cpu_vals) / n, 2),
            "cpu_percent_max": max(cpu_vals),
        }

    def analyze_system_telemetry(self) -> Dict[str, Any]:
        """Parse telemetry/system.csv for host-level resource consumption."""
        csv_file = self.run_dir / "telemetry" / "system.csv"
        if not csv_file.exists():
            return {"error": "system.csv not found"}

        cpu_vals: List[float] = []
        ram_vals: List[float] = []
        swap_vals: List[float] = []
        n = 0

        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    cpu_vals.append(float(row["cpu_percent"]))
                    ram_vals.append(float(row["ram_used_mb"]))
                    swap_vals.append(float(row["swap_used_mb"]))
                    n += 1
                except Exception:
                    continue

        if not cpu_vals:
            return {"error": "no valid samples in system.csv"}

        return {
            "sample_count": n,
            "host_cpu_mean_percent": round(sum(cpu_vals) / n, 2),
            "host_cpu_max_percent": max(cpu_vals),
            "host_ram_used_mean_mb": round(sum(ram_vals) / n, 2),
            "host_ram_used_max_mb": max(ram_vals),
            "host_swap_used_max_mb": max(swap_vals),
        }

    def analyze_checkpoints(self) -> Dict[str, Any]:
        """Audit all checkpoints in events/checkpoints.jsonl for mathematical conservation."""
        cp_file = self.run_dir / "events" / "checkpoints.jsonl"
        if not cp_file.exists():
            return {"error": "checkpoints.jsonl not found"}

        checkpoints: List[Dict[str, Any]] = []
        violations: List[Dict[str, Any]] = []

        with open(cp_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    cp = json.loads(line.strip())
                    checkpoints.append(cp)
                    gen = cp.get("generated", 0)
                    pers = cp.get("persisted", 0)
                    rej = cp.get("rejected", 0)
                    drop = cp.get("dropped", 0)
                    in_fl = cp.get("in_flight", 0)
                    loss = cp.get("silent_loss", 0)
                    if (pers + rej + drop + in_fl + loss) != gen or loss > 0:
                        violations.append(cp)
                except Exception:
                    continue

        return {
            "total_checkpoints": len(checkpoints),
            "all_conserved": len(violations) == 0,
            "violations_count": len(violations),
            "violations": violations,
            "last_checkpoint": checkpoints[-1] if checkpoints else {},
        }

    def analyze_anomalies_and_exceptions(self) -> Dict[str, Any]:
        """Audit exceptions and anomalies from events/exceptions.jsonl."""
        exc_file = self.run_dir / "events" / "exceptions.jsonl"
        exceptions: List[Dict[str, Any]] = []
        if exc_file.exists():
            with open(exc_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            exceptions.append(json.loads(line.strip()))
                        except Exception:
                            pass

        return {
            "total_exceptions_captured": len(exceptions),
            "exceptions": exceptions,
        }

    def evaluate_slos(self) -> Dict[str, Any]:
        """Evaluate overall compliance against configured SLO thresholds."""
        proc_stats = self.analyze_process_telemetry()
        cp_stats = self.analyze_checkpoints()
        anomalies = self.analyze_anomalies_and_exceptions()

        slos = self.config.get("slo_thresholds", {})
        raw_res_file = self.run_dir / "results" / "raw_results.json"
        raw_res = {}
        if raw_res_file.exists():
            with open(raw_res_file, "r", encoding="utf-8") as f:
                raw_res = json.load(f)

        slo_checks = []

        # 1. Silent Data Loss
        silent_loss = raw_res.get("silent_data_loss", cp_stats.get("last_checkpoint", {}).get("silent_loss", 9999))
        loss_passed = (silent_loss == 0) and cp_stats.get("all_conserved", False)
        slo_checks.append({
            "name": "Zero Silent Data Loss",
            "target": 0,
            "measured": silent_loss,
            "passed": loss_passed,
        })

        # 2. File Descriptor Growth
        fd_delta = proc_stats.get("fd_delta", 999)
        max_fd_delta = slos.get("max_fd_delta", 2)
        fd_passed = abs(fd_delta) <= max_fd_delta
        slo_checks.append({
            "name": "File Descriptor Stability",
            "target": f"<= {max_fd_delta}",
            "measured": fd_delta,
            "passed": fd_passed,
        })

        # 3. Memory Growth Rate
        mem_slope = proc_stats.get("rss_linear_regression_slope_mb_per_hr", 999.0)
        max_mem_slope = slos.get("max_memory_growth_rate_mb_per_hr", 1.0)
        actual_dur = float(self.manifest.get("actual_duration_seconds", 0.0))
        if actual_dur >= 1800.0:
            mem_passed = (mem_slope <= max_mem_slope)
        else:
            mem_passed = (proc_stats.get("rss_net_delta_mb", 999.0) <= 25.0)

        slo_checks.append({
            "name": "Memory Growth Rate (MB/hr)",
            "target": f"<= {max_mem_slope}",
            "measured": mem_slope,
            "passed": mem_passed,
        })

        # 4. SQLite Busy Errors
        busy_errors = raw_res.get("sqlite_busy_errors", 999)
        busy_passed = (busy_errors == 0)
        slo_checks.append({
            "name": "Zero SQLite Busy Errors",
            "target": 0,
            "measured": busy_errors,
            "passed": busy_passed,
        })

        # 5. Database Integrity Check
        db_integrity = raw_res.get("database_integrity_passed", False)
        slo_checks.append({
            "name": "Database Integrity & Foreign Keys",
            "target": "Passed",
            "measured": "Passed" if db_integrity else "Failed",
            "passed": db_integrity,
        })

        all_slos_passed = all(c["passed"] for c in slo_checks)

        evaluation = {
            "run_id": self.manifest["run_id"],
            "regime": self.manifest["regime"],
            "all_slos_passed": all_slos_passed,
            "slo_checks": slo_checks,
            "process_telemetry": proc_stats,
            "checkpoint_audit": cp_stats,
            "anomalies_audit": anomalies,
        }

        # Write results/slo_evaluation.json
        out_file = self.run_dir / "results" / "slo_evaluation.json"
        out_file.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")

        # Write results/anomalies.json
        anom_file = self.run_dir / "results" / "anomalies.json"
        anom_file.write_text(json.dumps(anomalies, indent=2), encoding="utf-8")

        return evaluation


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8E Offline Experiment Run Analyzer")
    parser.add_argument("--run-dir", type=Path, required=True, help="Path to experiment run directory")
    parser.add_argument("--verify-checksums", action="store_true", help="Verify SHA-256 evidence integrity")
    args = parser.parse_args()

    analyzer = RunAnalyzer(args.run_dir)
    if args.verify_checksums:
        ok, mismatches = analyzer.verify_checksums()
        if not ok:
            logger.error(f"Checksum verification failed: {mismatches}")
            sys.exit(1)
        logger.info("All SHA-256 checksums successfully verified.")

    eval_result = analyzer.evaluate_slos()
    logger.info(f"SLO Evaluation Complete. Overall Passed: {eval_result['all_slos_passed']}")
    for s in eval_result["slo_checks"]:
        status_str = "🟢 PASS" if s["passed"] else "🔴 FAIL"
        logger.info(f"  [{status_str}] {s['name']}: measured {s['measured']} (target {s['target']})")


if __name__ == "__main__":
    main()
