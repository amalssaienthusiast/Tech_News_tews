# Phase 8E: Cloud E1 Operational Reliability Soak Report

**Experiment**: Phase 8E — Cloud E1 (1-Hour Ingestion Soak)  
**Target Gate**: Phase 8E Operational Reliability  
**Role**: Senior / Principal Production Reliability Engineer  
**Repository**: `Tech_News_tews` (`https://github.com/amalssaienthusiast/Tech_News_tews.git`)  
**Commit SHA**: `9f79290b53a1bae77039a8e274b238ed4c53d623` (`9f79290`)  
**Branch**: `main` (in exact sync with `origin/main`)  
**Config Path**: `experiments/operational_reliability/configs/e1_smoke.json`  
**Config SHA-256**: `35da99c7ab7f0b2ead43d6993fc37cdca861c37801caadf27bac95d7c3dcb043`  
**Execution Timestamp**: `2026-08-19T16:07:00+05:30`  
**Experiment Verdict**: ⛔ **INVALID EXPERIMENT — E1 NOT EXECUTED (INVALID HOST)**  

---

## 1. Executive Summary & Host Invariant Gate

In strict adherence to the production reliability engineering contract and scientific reproducibility protocols, **Phase 8E Cloud E1 Operational Ingestion Soak was NOT executed on the local development workstation**.

The experiment protocol strictly mandates a dedicated, disposable **Ubuntu 24.04 LTS x86_64** cloud virtual machine with Docker Engine >= 24.0, Compose v2, 4+ vCPUs, and 8+ GB RAM. Local macOS execution must NEVER be fabricated or substituted for cloud execution.

---

## 2. Host Environment Preflight Fingerprint & Discrepancy

| Parameter | Required Cloud VM Specification | Observed Local Host Fingerprint | Evaluation |
|---|---|---|---|
| **Platform / OS** | Ubuntu 24.04 LTS (`Linux`) | macOS 26.6.2 (`Darwin 25.6.0`) | ❌ MISMATCH |
| **CPU Architecture** | `x86_64` | `arm64` (Apple Silicon) | ❌ MISMATCH |
| **Container Engine** | Docker Engine >= 24.0 | Not Installed (`docker not found`) | ❌ MISMATCH |
| **Docker Compose** | Compose v2.20+ | Not Installed (`docker-compose not found`) | ❌ MISMATCH |
| **Python Environment** | Python 3.12+ (Linux runtime) | Python 3.12.10 (Darwin arm64) | ⚠️ DEV HOST ONLY |
| **Git Working Tree** | Clean `main` (`9f79290`) | Clean `main` (`9f79290`) | 🟢 PASS |

---

## 3. Preflight Experiment Configuration Audit

- **Configuration File**: [`experiments/operational_reliability/configs/e1_smoke.json`](experiments/operational_reliability/configs/e1_smoke.json)
- **Target Ingestion Duration**: 3600.0 seconds (1 Hour)
- **Base Ingestion Rate**: 40.0 items/sec
- **Burst Overload Rate**: 500.0 items/sec (at T+1800s / 30m)
- **Source Fleet**: 100 heterogeneous technical sources
- **Worker Concurrency**: 8 parallel workers
- **Checkpoint Cadence**: Every 300.0 seconds (12 formal checkpoints across 1 hour)
- **Fault Injection Schedule**:
  - `T+900s` (15m): Active source lease expiration and successor worker takeover
  - `T+1800s` (30m): 500 items/sec ingestion burst (>138.6/s SQLite WAL capacity)
  - `T+2700s` (45m): 50% HTTP 429 rate-limiting storm with active backpressure
  - `T+3600s` (60m): Controlled pipeline drain and final data conservation audit

---

## 4. Operational Reliability Checkpoint Invariant Contract

When executed on a compliant Ubuntu cloud VM, E1 enforces the fundamental data conservation invariant across all 12 checkpoints:

$$	ext{Generated} = 	ext{Persisted} + 	ext{Rejected} + 	ext{Dropped} + 	ext{In\_Flight}$$

$$	ext{SilentLoss} = 0$$

All operational telemetry, file descriptors ($\Delta \le 2$), memory growth rate ($\le 1.0	ext{ MB/hr}$), SQLite WAL contention ($0	ext{ SQLITE\_BUSY}$), and FTS5 latency are verified by the offline analyzer [`analyze.sh`](experiments/operational_reliability/scripts/analyze.sh).

---

## 5. Experiment Verdict & Failure Classification

### Verdict: ⛔ **INVALID EXPERIMENT (E1 NOT EXECUTED — INVALID HOST)**

- **Classification**: **Category B: Infrastructure Limitation**.
- **Root Cause**: Host is a local Darwin arm64 workstation without Docker daemon rather than a provisioned Ubuntu 24.04 LTS x86_64 cloud VM.
- **Evidence Integrity**: No local runtime artifacts or synthetic numbers were fabricated.

---

## 6. Reproducibility & Cloud Execution Instructions

To execute Phase 8E Cloud E1 on a dedicated cloud VM:

1. **Provision Disposable VM**:
   ```bash
   # Minimum specs: Ubuntu 24.04 LTS x86_64, 4 vCPUs, 8 GB RAM, 40 GB SSD
   ```
2. **Clone Canonical Repository**:
   ```bash
   git clone https://github.com/amalssaienthusiast/Tech_News_tews.git
   cd Tech_News_tews
   git checkout main
   ```
3. **Bootstrap Toolchain**:
   ```bash
   bash experiments/operational_reliability/scripts/bootstrap.sh --install-system-deps
   ```
4. **Execute Cloud Runtime Acceptance Gate**:
   ```bash
   bash experiments/operational_reliability/scripts/cloud_acceptance_h4.sh
   ```
5. **Launch Controlled 1-Hour E1 Soak**:
   ```bash
   bash experiments/operational_reliability/scripts/run.sh --regime E1
   ```
6. **Perform Offline SLO Analysis**:
   ```bash
   bash experiments/operational_reliability/scripts/analyze.sh --latest
   ```
