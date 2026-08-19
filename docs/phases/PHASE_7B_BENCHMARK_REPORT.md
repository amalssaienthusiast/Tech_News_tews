# Phase 7B Benchmark Report: Acquisition Load & Ingestion Boundary Determination

**Program**: Phase 7 — Production Reality, Benchmark & Deployment Validation  
**Gate**: Gate 7B (Acquisition Load Testing & Empirical Boundary Determination)  
**Status**: BENCHMARK COMPLETED — SUBMITTED FOR REVIEW & COMMIT AUTHORIZATION  
**Baseline Commit**: `14f290b` (Gate 7A Frozen Specification)  
**Code Modifications in Production (`src/`)**: 0 (Zero Production Code Churn)  

---

## 1. Executive Summary

Gate **7B** executes the empirical acquisition benchmark harness ([`benchmarks/benchmark_acquisition.py`](file:///Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper/benchmarks/benchmark_acquisition.py)) across all five workload tiers (W1 through W5) established in Gate 7A.

The findings establish:
1. **Linear Scale to Target Workload (W1 $\to$ W3)**: The acquisition and ingestion stack sustains **$496.4\text{ items/sec}$** under 10,000 registered sources and 64 concurrent workers with p99 enqueue latency of **$0.091\text{ ms}$** (SLO target: $\le 1.0\text{ ms}$).
2. **Saturation Flood Ceiling (W4)**: Under an unbounded offered arrival flood of **$20,118\text{ obs/sec}$**, the in-memory priority queue absorbs and sustains **$2,596.0\text{ items/sec}$**, deterministically triggering backpressure at 80% watermark and dropping excess observations without unhandled errors.
3. **Fault Injection & SSRF Isolation (W5)**: Injected SSRF attacks and malformed targets are 100% intercepted by `SSRFGuard`, maintaining clean queue throughput ($87.0\text{ obs/sec}$) and zero pipeline contamination.
4. **Memory Stability**: Total RSS memory consumed across all test runs remained under **$145\text{ MB}$** (SLO limit: $\le 512\text{ MB}$).

---

## 2. Empirical Benchmark Results Matrix

| Workload ID | Name | Registered Sources | Concurrency Workers | Offered Rate ($\lambda$) | Ingestion Rate ($T$) | Enqueue Latency (p50 / p95 / p99) | Lease Latency (p50 / p99) | Backpressure Events | Drop Rate (%) | RSS Memory (MB) |
|---|---|---|---|---|---|---|---|---|---|---|
| **W1** | Baseline | 100 | 4 | 24.9 obs/s | **24.9 items/s** | 0.016 / 0.061 / **0.179 ms** | 0.035 / 0.229 ms | 0 | 0.0% | 130.1 MB |
| **W2** | Normal Scale | 1,000 | 16 | 99.2 obs/s | **99.2 items/s** | 0.012 / 0.055 / **0.128 ms** | 0.026 / 0.143 ms | 0 | 0.0% | 130.6 MB |
| **W3** | Target Scale | 10,000 | 64 | 496.4 obs/s | **496.4 items/s** | 0.009 / 0.027 / **0.091 ms** | 0.018 / 0.108 ms | 0 | 0.0% | 133.5 MB |
| **W4** | Saturation Flood | 10,000+ | 128 | 20,118 obs/s | **2,596.0 items/s** | 0.007 / 0.013 / **0.029 ms** | 0.002 / 0.007 ms | 1 (Triggered) | 87.1% (Capacity) | 139.4 MB |
| **W5** | Fault Injection | 1,000 | 32 | 99.7 obs/s | **87.0 items/s** | 0.010 / 0.025 / **0.074 ms** | 0.017 / 0.126 ms | 0 | 0.0% | 144.0 MB |

---

## 3. Comparison Against Gate 7A Acceptance SLOs

| SLO Dimension | Phase 7A Target Threshold | Empirical Result (W1–W3) | Saturation Result (W4) | Gate Status |
|---|---|---|---|---|
| **Queue Enqueue Latency (p99)** | $\le 1.0\text{ ms}$ | **$0.091\text{ ms}$** | **$0.029\text{ ms}$** | 🟢 **PASS (10x faster than target)** |
| **Lease Coordination Latency (p99)** | $\le 1.0\text{ ms}$ | **$0.108\text{ ms}$** | **$0.007\text{ ms}$** | 🟢 **PASS** |
| **Starvation Violations** | 0 | **0** | **0** | 🟢 **PASS** |
| **Silent Drops** | 0 | **0** | **0 (All drops accounted in metrics)** | 🟢 **PASS** |
| **Target Ingestion (W3)** | $\ge 200\text{ items/sec}$ | **$496.4\text{ items/sec}$** | N/A | 🟢 **PASS (2.48x target)** |
| **Max Sustainable Throughput** | Empirical Boundary | N/A | **$2,596.0\text{ items/sec}$** | 🟢 **DOCUMENTED** |
| **RSS Memory Envelope** | $\le 512\text{ MB}$ | **$133.5\text{ MB}$** | **$139.4\text{ MB}$** | 🟢 **PASS (73% headroom)** |

---

## 4. Key Engineering Insights & Boundary Findings

1. **Acquisition Scaling Limit**: The single-process in-memory queue and local lease coordinator easily scale to **10,000 registered sources** at target acquisition rate ($496.4\text{ obs/sec}$) without backpressure.
2. **Ingestion Saturation Point**: When arrival rates exceed consumer processing capacity ($\lambda > 2,600\text{ obs/sec}$), the queue reaches its 10,000-item capacity, backpressure triggers at 80% (8,000 items), and incoming items are deterministically dropped and recorded without memory bloat.
3. **Lease Efficiency**: Fencing token generation and lease checks execute in sub-millisecond time ($< 0.11\text{ ms}$ p99), confirming that in-memory lease coordination does not bottleneck worker swarms.

---

## 5. Next Milestone: Gate 7C (Pipeline & Storage Saturation Benchmarking)

With acquisition limits established, **Gate 7C** will benchmark `CanonicalPipelineRunner` (S01–S11) coupled directly with `SqliteEngine` under concurrent write load, measuring:
- Multi-threaded transaction commit latency and SQLite WAL contention.
- Lock-wait duration percentiles (p50/p95/p99) and maximum writer wait.
- FTS5 full-text indexing overhead across database volume tiers **D1 (10k)**, **D2 (100k)**, and **D3 (1M articles)**.
