# Phase 7A Benchmark Architecture & Workload Specification

**Program**: Phase 7 — Production Reality, Benchmark & Deployment Validation  
**Gate**: Gate 7A (Benchmark Architecture & Workload Specification)  
**Status**: SUBMITTED FOR REVIEW & BASELINE APPROVAL  
**Baseline Commit**: `f47d972` (Phase 6 Frozen)  
**Code Modifications in 7A**: 0 (Specification & Experimental Controls Only)  

---

## 1. Executive Summary & Objective

Phase 7 transitions the project from **capability construction** to **empirical boundary determination, stress measurement, fault tolerance, and operational deployment**.

Gate **7A** establishes the mathematical workload models, Service Level Objectives (SLOs), saturation criteria, and experimental controls that govern all Phase 7 benchmark executions (7B through 7H).

```
                            PHASE 7 BENCHMARK LIFECYCLE
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  Workload Models                  Explicit SLOs                 Saturation Metrics
 (W1: 100 Baseline                (p50/p95/p99 Latency,         (Throughput Plateau,
  W2: 1k Scale                     Throughput, Drop Rates,       Latency Knee, Queue Creep,
  W3: 10k Target                   Storage IOPS, Memory)         Resource Exhaustion)
  W4: Saturation Flood
  W5: Fault Injected)
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         │
                                         ▼
                            Experimental Governance
                         (Git Commit, Environment, Seeds,
                          Zero Churn Without Evidence)
```

---

## 2. Workload Models & Database Volume Profiles

Workloads are defined along two orthogonal axes: **Offered Ingestion Load (W1–W5)** and **Database Volume Profiles (D1–D4)**:

### 1. Ingestion Load Profiles (W1 through W5)
| Workload ID | Name | Registered Sources | Active Concurrency | Target Ingestion Rate | Payload Profile | Purpose |
|---|---|---|---|---|---|---|
| **W1** | **Baseline** | 100 | 4 workers | 10–25 obs/sec | 5–20 KB standard RSS | System baseline & calibration |
| **W2** | **Normal Scale** | 1,000 | 16 workers | 50–100 obs/sec | 5–50 KB mixed RSS/HTML | Production steady-state simulation |
| **W3** | **Target Scale** | 10,000 | 64 workers | 200–500 obs/sec | 5–100 KB multi-species | Maximum design capacity evaluation |
| **W4** | **Saturation Flood** | 10,000+ | Unbounded (256+) | Maximum possible ($\lambda \to \infty$) | Random 1 KB – 2 MB | Identify break points, drops & backpressure |
| **W5** | **Resilience / Fault Injection** | 1,000 | 32 workers | 100 obs/sec | 20% malformed, 10% SSRF, 10% timeouts | Verify failure isolation & recovery |

### 2. Database Volume Profiles (D1 through D4)
| Volume Tier | Stored Articles | Stored Tech Events | Est. DB Size | Purpose |
|---|---|---|---|---|
| **D1** | **10,000** | 2,500 | ~25 MB | Initial startup / dev baseline |
| **D2** | **100,000** | 25,000 | ~250 MB | Production baseline volume |
| **D3** | **1,000,000** | 250,000 | ~2.5 GB | Intermediate scale (index caching limits) |
| **D4** | **10,000,000** | 2,500,000 | ~25 GB | Large scale stress (FTS5 BM25 memory ceiling) |

---

## 3. Quantitative Service Level Objectives (Benchmark Acceptance Targets)

All benchmarks evaluate the system against explicit **Benchmark Acceptance Targets / Experimental Thresholds** (to be empirically validated):

### 1. Acquisition & Network Layer
- **DNS Resolution Latency**: Target p50 $\le 10\text{ ms}$, p99 $\le 50\text{ ms}$.
- **SSRF Validation Overhead**: Target p99 $\le 2\text{ ms}$ per candidate URL.
- **Fetch Latency (Simulated LAN/WAN)**: Target p50 $\le 150\text{ ms}$, p95 $\le 500\text{ ms}$, p99 $\le 1500\text{ ms}$.
- **Lease Contention Overwrites**: **0** (fencing token invariant).

### 2. Ingestion & Priority Queue
- **Queue Enqueue Latency**: Target p99 $\le 1\text{ ms}$.
- **Queue Wait Latency (Normal Load)**: Target p50 $\le 20\text{ ms}$, p99 $\le 200\text{ ms}$.
- **Starvation Violations**: **0** (aging algorithm guarantee).
- **Backpressure Hysteresis Compliance**: Activates at $\ge 80\%$, deactivates at $\le 60\%$.
- **Silent Drops**: **0** (all drops accounted for in `technews_queue_items_dropped_total`).

### 3. Canonical Pipeline (S01–S11)
- **Total Pipeline Execution Latency**: Target p50 $\le 10\text{ ms}$, p95 $\le 25\text{ ms}$, p99 $\le 50\text{ ms}$.
- **Stage Isolation**: Unhandled exceptions in individual stages $\le 0.001\%$.
- **Context Leakage**: **0** (cross-observation state contamination).

### 4. Storage Engine & SQLite/FTS5 Contention
- **Article Insert Transaction Latency**: Target p50 $\le 5\text{ ms}$, p99 $\le 25\text{ ms}$.
- **`SQLITE_BUSY` Errors**: **0** (guaranteed by busy_timeout = 10,000 ms).
- **Lock Wait Events & Latency**:
  - Lock contention event frequency: Explicitly measured ($\text{events/sec}$).
  - Lock wait duration: Target p50 $\le 2\text{ ms}$, p95 $\le 15\text{ ms}$, p99 $\le 50\text{ ms}$.
  - Max single writer wait: Target $\le 200\text{ ms}$.
- **FTS5 Index Trigger Overhead**: $\le 30\%$ of total insert time.
- **FTS5 Search Query Latency**: Target p50 $\le 2\text{ ms}$, p95 $\le 10\text{ ms}$, p99 $\le 25\text{ ms}$ across D1–D3.

### 5. Resource Envelope & Telemetry Bounds
- **Resident Set Size (RSS)**: Target $\le 512\text{ MB}$ under steady-state load (W1–W3).
- **Memory Growth Rate**: Target $\le 10\text{ MB/hour}$ continuous gradient.
- **Prometheus Metric Series Cardinality**: Strictly bounded ($< 200$ total active time series).
- **File Descriptors / Sockets**: $\le 1024$ open handles.

---

## 4. Mathematical Saturation & Boundary Definition

A system component is defined as **SATURATED** when any of the following boundary conditions occur:

$$\text{SATURATED} \iff \begin{cases}
\text{Condition 1 (Throughput Knee):} & \frac{\Delta T}{\Delta \lambda} = \frac{T_{k+1} - T_k}{\lambda_{k+1} - \lambda_k} \le 0.05 \quad (\text{sustained over } \ge 3 \text{ consecutive measurement windows}) \\
\text{Condition 2 (Latency Breach):} & \text{Latency}_{p99} \ge 2.0 \times \text{SLO}_{p99} \\
\text{Condition 3 (Queue Overflow):} & \frac{d Q}{d t} > 0 \quad (\text{Queue depth grows unbounded}) \\
\text{Condition 4 (Memory Breach):} & \text{Memory}_{\text{RSS}} > 768\text{ MB} \quad (\text{Memory ceiling breach}) \\
\text{Condition 5 (Instability):} & \text{Error Rate} > 1.0\% \quad (\text{Excluding intentional fault injection})
\end{cases}$$

When saturation occurs, the benchmark harnesses record the exact saturation threshold:
- **Maximum Sustainable Ingestion Rate**: $T_{\text{max}}$ (articles/sec).
- **Maximum Concurrent Source Capacity**: $C_{\text{max}}$ (active sources).
- **Storage Write Saturation Ceiling**: $W_{\text{max}}$ (commits/sec).

---

## 5. Experimental Controls & Reproducibility Matrix

To ensure absolute comparability between benchmark runs, every execution harness automatically records:

```json
{
  "benchmark_metadata": {
    "git_commit": "f47d972...",
    "timestamp_utc": "2026-08-16T12:00:00Z",
    "python_version": "3.12.10",
    "platform": "Darwin-25.2.0-arm64",
    "cpu_cores": 10,
    "ram_total_bytes": 34359738368,
    "sqlite_version": "3.46.1",
    "sqlite_compile_options": ["ENABLE_FTS5", "ENABLE_JSON1", "THREADSAFE=1"],
    "wal_autocheckpoint": 1000,
    "busy_timeout_ms": 10000,
    "workload_id": "W2",
    "random_seed": 42,
    "test_duration_seconds": 60.0
  }
}
```

---

## 6. Phase 7 Execution Progression

```text
Gate 7A: Benchmark Architecture & Workload Specification (Current Gate)
   │
   ▼
Gate 7B: Acquisition Load Testing (W1 -> W2 -> W3 Source Scaling)
   │
   ▼
Gate 7C: Pipeline & Storage Saturation Benchmarking (SQLite Contention & FTS5 Indexing)
   │
   ▼
Gate 7D: Distributed Worker & Fault Injection (Multi-Process & Crash Recovery)
   │
   ▼
Gate 7E: Long-Running Soak & Memory Profiling (6h / 24h Continuous Ingestion)
   │
   ▼
Gate 7F: Disaster Recovery, WAL Replay & Poison Payload Remediation
   │
   ▼
Gate 7G: Production Deployment Engineering (Containerization & Runbooks)
   │
   ▼
Gate 7H: Final Production Readiness Review & Operational Sign-off
```

---

## 7. Governance & Architectural Non-Regression Rule

1. **No Speculative Rewrites**: A benchmark finding a performance limit or bottleneck does **not** authorize ad-hoc modifications to frozen Phase 5 or Phase 6 code.
2. **Empirical Evidence First**: Every proposed optimization must be preceded by a reproducible benchmark trace, flamegraph, or metric delta demonstrating the bottleneck.
3. **Formal Gate Approval**: Any architectural adjustment requires an explicit gate review with before-and-after benchmark comparisons.

---

## 8. Gate 7A Recommendation

Gate **7A** establishes an uncompromising, mathematically grounded benchmark standard for evaluating the production limits of the Tech News Scrapper platform.

**Gate 7A Status**: **SUBMITTED FOR REVIEW & BASELINE APPROVAL** ✅  
**Ready for**: **Gate 7B (Acquisition Load Testing Implementation)**.
