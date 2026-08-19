# Phase 8E: Cloud Operational Reliability Experimental Infrastructure

This directory contains the completely isolated, scientifically reproducible experimental laboratory for executing long-duration operational reliability benchmarks (Regimes E1 through E6) on dedicated cloud VM hosts.

---

## 1. Experimental Philosophy & Architecture

```text
DEVELOPMENT HOST (Mac)
       │
       │ git commit
       ▼
CLOUD BENCHMARK HOST (Ubuntu/Debian VM)
       │
       ├── 1. ./scripts/bootstrap.sh (environment verification & dependencies)
       ├── 2. ./scripts/run.sh --regime E2 (isolated soak execution)
       │       ├── Captures full OS, hardware, Python, and Git fingerprint
       │       ├── Streams 4-layer telemetry (System, Process, App, SQLite)
       │       ├── Audits strict observation conservation checkpoints
       │       ├── Emits final summary, reports, and SHA-256 checksums
       │       └── Preserves all evidence in an immutable run directory
       │
       ▼
IMMUTABLE RUN ARTIFACTS (`runs/<RUN_ID>/`)
       │
       │ scp/download to Mac
       ▼
OFFLINE POST-RUN ANALYSIS (`./scripts/analyze.sh`)
       │
       ├── Statistical memory regression slope
       ├── FTS5 stratified write-contention profile
       ├── Database WAL and PRAGMA integrity audit
       └── Empirical bottleneck identification
```

### Core Invariants:
1. **Zero Production Code Churn**: No files under `src/` are modified or mutated by benchmarks.
2. **Strict Run Isolation**: Every execution writes exclusively into its own self-contained directory under `runs/<RUN_ID>/`. It never alters production databases.
3. **100% Offline Analyzability**: Post-run analysis utilities operate purely on saved filesystem artifacts without querying live databases or running services.
4. **Append-Only Evidence**: Telemetry is written as append-only CSV and JSONL files with immediate flush semantics to survive unexpected process crashes or VM reboots.

---

## 2. Directory Structure

```text
experiments/operational_reliability/
├── README.md                           # This operational manual
├── schemas/
│   ├── __init__.py
│   └── manifest_schema.json            # JSON schema for RUN_MANIFEST.json
├── configs/
│   ├── smoke_test.json                 # 30s local verification config
│   ├── e1_smoke.json                   # 1-Hour smoke soak config
│   ├── e2_6h.json                      # 6-Hour resource & descriptor stability
│   ├── e3_24h.json                     # 24-Hour operational soak
│   ├── e4_72h.json                     # 72-Hour extended reliability
│   ├── e5_7d.json                      # 7-Day operational confidence
│   └── e6_30d.json                     # 30-Day production evidence
├── collectors/
│   ├── __init__.py
│   ├── system_collector.py             # Host CPU, Load, RAM, Swap, Disk, Network
│   ├── process_collector.py            # Process RSS, VMS, CPU, Threads, FDs, GC
│   ├── application_collector.py        # Structured JSON logs, events, exceptions
│   └── database_collector.py           # SQLite size, WAL size, page count, PRAGMA checks
├── runners/
│   ├── __init__.py
│   ├── environment_fingerprint.py      # Full hardware, OS, Python, SQLite fingerprinting
│   ├── workload_executor.py            # Ingestion pipeline & fault supervisor
│   └── experiment_runner.py            # Orchestrator & lifecycle manager
├── analysis/
│   ├── __init__.py
│   └── run_analyzer.py                 # Offline evidence consumer & SLO evaluator
├── scripts/
│   ├── bootstrap.sh                    # Cloud VM provisioning script
│   ├── run.sh                          # CLI runner wrapper
│   └── analyze.sh                      # CLI offline analysis wrapper
└── runs/                               # Standalone run directories (ignored by Git)
    └── .gitkeep
```

---

## 3. Structure of a Self-Contained Run Directory

Every experiment execution creates a dedicated folder under `runs/<TIMESTAMP>_<REGIME>_<HASH>/`:

```text
runs/20260817T043000Z_E2_a7f92c10/
├── RUN_MANIFEST.json                   # Topline manifest & environment fingerprint
├── environment/                        # Raw environment dumps
│   ├── git.txt
│   ├── python.txt
│   ├── pip-freeze.txt
│   ├── os-release.txt
│   ├── kernel.txt
│   ├── cpu.txt
│   ├── memory.txt
│   ├── disk.txt
│   ├── sqlite.txt
│   └── docker.txt
├── configuration/                      # Experiment input parameters
│   ├── workload.json
│   └── benchmark_config.json
├── application/                        # Application logs
│   ├── application.jsonl
│   ├── stdout.log
│   └── stderr.log
├── telemetry/                          # Time-series metrics
│   ├── system.csv
│   ├── process.csv
│   └── prometheus_snapshot.txt
├── database/                           # SQLite state & health audits
│   ├── app.db
│   ├── coord.db
│   ├── sqlite_stats.json
│   └── integrity_check.txt
├── events/                             # Event streams
│   ├── checkpoints.jsonl
│   ├── fault_injections.jsonl
│   ├── worker_events.jsonl
│   ├── recovery_events.jsonl
│   └── exceptions.jsonl
├── results/                            # Computed summaries
│   ├── raw_results.json
│   ├── summary.json
│   ├── slo_evaluation.json
│   └── anomalies.json
└── final/                              # Human report and cryptographic verification
    ├── FINAL_REPORT.md
    └── checksums.sha256
```

---

## 4. Standard Operating Procedure (SOP)

### Step 1: Provision Cloud VM (Ubuntu / Debian LTS)
On a clean cloud VM instance (e.g. 2–4 vCPUs, 8–16 GB RAM, 50 GB SSD):

```bash
git clone <REPO_URL> Tech_News_Scrapper
cd Tech_News_Scrapper
git checkout <FROZEN_COMMIT_SHA>

# Bootstrap runtime dependencies and run verification self-test:
./experiments/operational_reliability/scripts/bootstrap.sh
```

### Step 2: Execute Soak Regime
Launch the required regime in a persistent session (e.g. `tmux` or `systemd-run`):

```bash
# Example: Execute 6-Hour Regime E2
./experiments/operational_reliability/scripts/run.sh --regime E2

# Example: Execute 24-Hour Regime E3
./experiments/operational_reliability/scripts/run.sh --regime E3
```

### Step 3: Run Offline Analysis
Analyze the generated run folder locally or after transferring back to the development machine:

```bash
# Analyze the most recent run:
./experiments/operational_reliability/scripts/analyze.sh --latest

# Or analyze a specific run directory:
./experiments/operational_reliability/scripts/analyze.sh --run-dir experiments/operational_reliability/runs/<RUN_ID>
```

---

## 5. Mathematical Conservation Invariant

Every checkpoint throughout the experiment audits:
$$\text{Generated} = \text{Persisted} + \text{Explicitly\_Rejected} + \text{Explicitly\_Dropped} + \text{In\_Flight}$$

Any deviation where $\text{Silent\_Data\_Loss} > 0$ triggers an immediate hard experiment failure.
