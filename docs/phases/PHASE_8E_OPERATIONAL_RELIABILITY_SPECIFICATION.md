# Phase 8E Specification: Long-Term Operational Reliability & Soak Architecture

**Program**: Phase 8 — Real-World Productionization & Internet Operations  
**Gate**: Gate 8E-A (Operational Reliability Architecture & Soak Specification)  
**Status**: FROZEN SPECIFICATION — AMENDED & FROZEN FOR IMPLEMENTATION  
**Baseline Commit**: `50c6f15` (Gate 8D Frozen)  
**Code Modifications in Production (`src/`)**: 0 (Specification & Design Phase)  

---

## 1. Purpose & Experimental Scope

Phase 7 and early Phase 8 gates established that the Tech News Scrapper handles peak burst loads ($\approx 2,596\text{ items/s}$ ingestion), SQLite WAL canonical persistence ceiling ($\approx 138.6\text{ articles/s}$), multi-process coordination ($0\text{ split-brain}$ across 8 PIDs), and dynamic discovery ($1,355\text{ candidate operations}$).

**Gate 8E** evaluates the continuous, longitudinal behavior of the integrated system over extended timeframes when operating unassisted under continuous source churn, network jitter, transient failures, and background maintenance.

The primary experimental objective is to verify that:
$$\frac{d(\text{Memory})}{dt} \approx 0, \quad \frac{d(\text{Descriptors})}{dt} = 0, \quad \text{Series}_{\text{Prometheus}}(t) = O(1), \quad \text{SplitBrain} = 0, \quad \text{DataLoss} = 0$$

---

## 2. Soak Regimes & Gated Execution Progression (8E-A through 8E-I)

Phase 8E execution is strictly staged and gated. If any stage fails, testing halts for root-cause investigation before proceeding to subsequent durations:

```text
8E-A  Specification Freeze
       │
       ▼
8E-B  Harness Implementation (Ledger + Supervisor)
       │
       ▼
8E-C  Regime E1 — 1 Hour Smoke
       │
       ├── FAIL → Investigate & Fix
       │
       ▼
8E-D  Regime E2 — 6 Hours Resource Stability
       │
       ├── FAIL → Investigate & Fix
       │
       ▼
8E-E  Regime E3 — 24 Hours Operational Soak
       │
       ▼
8E-F  Regime E4 — 72 Hours Extended Reliability
       │
       ▼
8E-G  Regime E5 — 7 Days Operational Confidence
       │
       ▼
8E-H  Regime E6 — 30 Days Production Evidence
       │
       ▼
8E-I  Operational Reliability Report Closeout
```

| Regime | Test Identifier | Duration | Source Fleet | Offered Rate | Primary Purpose |
|---|---|---|---|---|---|
| **E1** | **Smoke Operational Lifecycle** | 1 Hour | 100 Sources | $40\text{ items/s}$ | Sanity check end-to-end telemetry, ledger accounting, and recovery |
| **E2** | **Resource & Descriptor Stability** | 6 Hours | 500 Sources | $80\text{ items/s}$ | Verify linear memory gradient $\le 1.0\text{ MB/hr}$ and constant FD count |
| **E3** | **Real Operational Soak** | 24 Hours | 1,000 Sources | $120\text{ items/s}$ | Continuous day-long run with diurnal traffic curve and churn |
| **E4** | **Extended Reliability Fleet** | 72 Hours (3 Days) | 1,500 Sources | $130\text{ items/s}$ | Multi-day fleet stability, WAL checkpointing, and vacuuming |
| **E5** | **Operational Confidence** | 7 Days (1 Week) | 2,000 Sources | $135\text{ items/s}$ | Weekly reliability baseline and log volume growth analysis |
| **E6** | **Production Evidence Benchmark** | 30 Days (1 Month) | 5,000+ Sources | Dynamic / Real | Final production longitudinal proof before Phase 8I certification |

---

## 3. Regime-Specific Fault Injection Schedules

To ensure deterministic and reproducible fault evaluation, fault schedules are defined specifically per regime duration:

### Regime E1 Schedule (60 Minutes)
- **T+15m**: Sudden Zombie Worker PID crash (`SIGKILL` simulation / task abort).
- **T+30m**: Overload burst arrival ($500\text{ items/s} \gg 138.6\text{ articles/s}$ persistence ceiling).
- **T+45m**: $50\%$ HTTP 429 Too Many Requests storm (verifying backoff & recovery).

### Regime E2 Schedule (6 Hours)
- **T+30m**: Worker crash and successor lease takeover.
- **T+60m**: Queue backpressure saturation & drainage test.
- **T+90m**: 429 storm & exponential retry recovery.
- **T+120m**: Transient DNS resolution failure injected on $20\%$ of sources.
- **T+180m**: Poisoned / corrupt XML & JSON payload stream injection.
- **T+240m**: API container / process restart & health restoration.

### Regime E3+ Schedule (24 Hours+)
- Repeated, pseudo-randomized fault injection sequence mimicking diurnal internet anomalies.

---

## 4. Stratified FTS5 Search Latency SLOs

In accordance with Phase 7C-D empirical findings (which attributed FTS5 search degradation under write saturation to SQLite WAL lock waiting rather than search indexing), FTS5 latency is stratified across 3 distinct operating conditions:

| Operating Regime | Description | Target Latency SLO | Disqualification Threshold |
|---|---|---|---|
| **SLO A: Read-Isolated** | Background write load idle ($0\text{ writes/s}$) | $\text{p95} \le 2.0\text{ ms}$ | $\text{p95} > 5.0\text{ ms}$ |
| **SLO B: Normal Load** | Continuous write load $\le 100\text{ writes/s}$ | $\text{p95} \le 10.0\text{ ms}$ | $\text{p95} > 25.0\text{ ms}$ |
| **SLO C: Saturated Load** | Ingestion burst $> 138.6\text{ articles/s}$ | Document degradation ($\approx 80\text{--}120\text{ ms}$) | Unhandled timeout / error |

---

## 5. Harmonized Resource & Telemetry SLOs

| Metric Category | Target / Excellent | Acceptable (PASS) | Warning / Investigate | Hard Disqualification (FAIL) |
|---|---|---|---|---|
| **Memory Growth Rate** | $\le 0.5\text{ MB / hour}$ | $0.5\text{--}1.0\text{ MB / hour}$ | $1.0\text{--}2.0\text{ MB / hour}$ | $\ge 2.0\text{ MB / hour}$ (or monotonic $>1\text{MB/hr}$ across 6h) |
| **Steady-State RSS** | $\le 150\text{ MB}$ | $\le 200\text{ MB}$ | $200\text{--}350\text{ MB}$ | $\ge 500\text{ MB}$ |
| **Open File Descriptors** | Constant ($\Delta \text{FD} = 0$) | $\Delta \text{FD} \le 2$ | $\Delta \text{FD} = 3\text{--}5$ | Monotonic uncurbed FD leak |
| **Prometheus Series Count**| Constant ($O(1)$) | $\le 300\text{ series}$ | $300\text{--}500\text{ series}$ | Unbounded cardinality growth |
| **Log Volume Growth** | $\le 50\text{ MB / day}$ | $\le 100\text{ MB / day}$ | $100\text{--}250\text{ MB / day}$ | Unbounded debug spam |
| **SQLite Busy Errors** | $0$ | $0$ | $\ge 1$ (transient retry) | Unhandled busy crash |

---

## 6. Formal Observation Ledger & Silent Data-Loss Accounting

To make data integrity mathematically verifiable, the soak harness maintains an immutable **Observation Ledger**:

```text
Generated Observations
         │
         ├── Enqueued in PriorityQueue
         │        │
         │        ├── Dropped by Backpressure (explicitly recorded)
         │        ▼
         ├── Dequeued by Pipeline
         │        │
         │        ├── Rejected by Normalizer / S04 Quality (explicitly recorded)
         │        ▼
         └── Persisted to SQLite WAL & FTS5 (explicitly recorded)
```

### Mandatory Conservation Invariant:
$$\text{Total\_Generated} = \text{Persisted} + \text{Explicitly\_Rejected} + \text{Explicitly\_Dropped} + \text{In\_Flight}$$

$$\text{Silent\_Data\_Loss} = \text{Total\_Generated} - (\text{Persisted} + \text{Explicitly\_Rejected} + \text{Explicitly\_Dropped} + \text{In\_Flight})$$

**Hard Failure Condition**: Any run where $\text{Silent\_Data\_Loss} > 0$ is immediately declared an **UNCONDITIONAL FAILURE**.

---

## 7. Dynamic Source Churn Model

```text
100 Seed Sources ──► Scale to 500 ──► Scale to 1,000 ──► Retire 100 ──► Add 500 Vetted ──► Inject 20% Failures ──► Self-Heal
```
- Sources experiencing persistent 5xx/404 errors for $> 24\text{ hours}$ transition via Discovery FSM to `QUARANTINED` $\to$ `RETRY_LATER`.
- New candidate feeds from Gate 8D autodiscovery are vetted and dynamically promoted into the `SqliteSwarmCoordinator` shard partition.

---

## 8. Self-Healing & Incident Response Targets

- **MTTD (Mean Time to Detect)**: $\le 5.0\text{ seconds}$.
- **MTTR (Mean Time to Recover)**: $\le 15.0\text{ seconds}$.
- **Orphaned Lease Takeover**: Successor worker acquires lease within $\text{TTL} + 0.5\text{ seconds}$.
- **Split-Brain Rejection**: $0$ duplicate writes permitted during worker failover.

---

## 9. Next Steps

1. **Commit Amended Specification**: Freeze `PHASE_8E_OPERATIONAL_RELIABILITY_SPECIFICATION.md`.
2. **Gate 8E-B**: Implement benchmark harness in `benchmarks/benchmark_operational_soak.py` and test suite in `tests/test_operational_soak.py`.
3. **Gate 8E-C**: Execute Regime E1 (1-Hour Smoke) and report findings.
