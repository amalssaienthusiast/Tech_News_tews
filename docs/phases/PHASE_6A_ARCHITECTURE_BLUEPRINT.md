# Phase 6A: Architecture Blueprint, Production Topology & Phase 5 Compatibility Review

**Program**: Phase 6 — Internet-Scale Acquisition, Search, Security & Production Operations  
**Gate**: Gate 6A (Architecture Blueprint & Production Topology)  
**Status**: 🟢 **APPROVED WITH CONDITIONS (Authorized for 6B Progression)**  
**Baseline Commit**: `afb66cc` (Phase 5 Frozen 🔒)  
**Code Modifications in 6A**: 0 (Design & Blueprint Gate Only)  

---

## 1. Executive Vision & Scope

Phase 5 successfully established the **Canonical Memory Foundation**: a single, crash-resilient SQLite database (`canonical_events.db`), strict repository protocols, and the 11-stage `CanonicalPipelineRunner`.

**Phase 6** expands this foundation to **Internet-Scale Production Readiness**. The objective is to build a continuously active, globally sourced, secure, low-latency tech news intelligence platform capable of ingesting from thousands of heterogeneous sources without sacrificing data integrity, memory stability, or Phase 5 invariants.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               PHASE 6 ARCHITECTURE                              │
└─────────────────────────────────────────────────────────────────────────────────┘
                                   INTERNET
                                      │
                   ┌──────────────────┴──────────────────┐
                   ▼                                     ▼
        Distributed Zombie Swarm                Webhook & PubSub Ingestion
     (Partitioned / Leased Tasks)                (Push-Based Realtime)
                   │                                     │
                   └──────────────────┬──────────────────┘
                                      ▼
                        SSRF & Sanitization Gateway
                    (DNS Pinning, Private IP Defense)
                                      │
                                      ▼
                   Starvation-Safe Prioritized Queue
                   (CRITICAL, HIGH, NORMAL, LOW)
                                      │
                                      ▼
                      CanonicalPipelineRunner (S01 → S11)
                                      │
                   ┌──────────────────┼──────────────────┐
                   ▼                  ▼                  ▼
        ArticleRepository       EventRepository   SourceHealthRepository
        (CRUD + FTS5 Search)   (Cluster Timeline) (Adaptive Feedback)
                   │                  │                  │
                   └──────────────────┼──────────────────┘
                                      ▼
                             SqliteEngine (WAL)
                                      │
                                      ▼
                            canonical_events.db
                                      │
                   ┌──────────────────┴──────────────────┐
                   ▼                                     ▼
          FastAPI Backend (REST)                 SSE Broadcast Stream
          (OAuth2 / Rate Limited)                 (Live Cluster Feed)
                   │                                     │
                   ▼                                     ▼
          Web / API Consumers                   Qt Desktop / Monitor
```

---

## 2. Gate 6A Formal Decisions & 6B Mandatory Acceptance Criteria

### 6A-01: Production Topology & Measured Capacity Envelope
- **Topology Model**: Tiered topology.
  - *Tier 1 (Single-Host Baseline)*: Multi-process async task supervisor + bounded queue + single WAL `SqliteEngine`.
  - *Tier 2 (Multi-Node Scaling)*: External coordinator + distributed proxies activated **only** when empirical single-node limits are reached.
- **Mandatory 6B Condition**: Quantitative claims are treated as benchmark targets, not assumptions. Subphase 6B will establish empirical benchmarks for sustained writes/sec, burst handling, WAL growth, and observation throughput.

---

### 6A-02: Zombie Swarm Scaling & Coordination Boundaries
- **Ownership Model**:
  - *Single-Host Deployment*: In-memory atomic lease table or SQLite atomic row leases (`lease_owner`, `lease_expiry`).
  - *Multi-Node Deployment*: External coordination layer (e.g., Redis/etcd lease protocol) decoupled behind an abstract `SwarmCoordinatorProtocol`.
- **Mandatory 6B Condition**: SQLite leases are restricted to single-host coordination; distributed coordination remains behind an abstract protocol to avoid coupling global distributed state directly to SQLite.

---

### 6A-03: Freshness Architecture & Dual Latency Metric
- **Latency Distinction**:
  - $T_{\text{external}}$ (*Uncontrollable*): Real-world publisher time to crawler discovery (governed by RSS publication delay, CDN caching, and polling frequency).
  - $T_{\text{internal}}$ (*Controllable SLA*): Time from crawler receipt to S10 SSE broadcast.
- **Mandatory 6B Condition**: Target internal latency SLA is structured as:
  - $P_{50} \le 250\text{ ms}$
  - $P_{95} \le 750\text{ ms}$
  - $P_{99} \le 1,500\text{ ms}$

---

### 6A-04: Global Discovery & Source Lifecycle FSM
- **Lifecycle Separation**:
  - **Source Discovery FSM**: `DISCOVERED` $\to$ `VETTING` $\to$ `QUARANTINED` $\to$ `PROMOTED` (or `REJECTED` permanently to prevent rediscovery loops).
  - **Source Runtime Health FSM**: `HEALTHY` $\leftrightarrow$ `DEGRADED` $\leftrightarrow$ `SUSPENDED` (managed independently by `SourceHealthRepository`).
- **Mandatory 6B Condition**: Discovery state transitions and runtime health state transitions remain separate, with an immutable `REJECTED` blacklist table.

---

### 6A-05: Starvation-Safe Backpressure & Flow Control
- **Priority Classes**:
  - `CRITICAL` (Push webhooks, breaking tier-1 alerts)
  - `HIGH` (Tier-1 major tech publications)
  - `NORMAL` (Standard RSS feeds, blogs)
  - `LOW` (Discovery probes, deep crawling)
- **Mandatory 6B Condition**: Flow-control implements weighted fair queuing with anti-starvation guarantees (e.g., 1 LOW processed per $K$ CRITICAL items) and dynamic scheduler backoff when queue capacity exceeds 80%.

---

### 6A-06: High-Scale Search Architecture (FTS5 as Layer 1)
- **Search Boundaries**:
  - *Phase 6C Lexical Search*: Native SQLite FTS5 virtual tables with BM25 ranking and snippet generation within `SqliteArticleRepository`.
  - *Deferred Semantic Search*: Vector embedding generation and dedicated ANN indexes are deferred to a separate pluggable interface without altering core repository contracts.
- **Mandatory 6B Condition**: FTS5 performance is benchmarked empirically against article archive scale.

---

### 6A-07: Observability & Distributed Trace Contracts
- **Correlation Context**: All logs, events, and metrics must carry:
  - `trace_id` (Unique per ingestion session)
  - `worker_id` (Zombie worker identifier)
  - `source_id` (Target domain/feed)
  - `observation_id` (Unique per fetched payload)
  - `pipeline_run_id` (Canonical pipeline execution identifier)
  - `article_id` / `event_id` (Downstream canonical entity IDs)
- **Mandatory 6B Condition**: OpenTelemetry-compatible span context propagated through `SourceObservation.metadata`.

---

### 6A-08: Failure Domains & SQLite Recovery Hierarchy
- **Recovery Hierarchy**:
  1. *Payload Failure*: Isolate bad payload to `quarantine_articles`, log structured error, continue pipeline.
  2. *Worker Crash*: Stateless restart, expired lease auto-reclaimed by surviving workers.
  3. *Process Crash / Power Loss*: Automatic SQLite WAL recovery on connection open.
  4. *WAL Maintenance*: Periodic passive checkpointing (`PRAGMA wal_checkpoint(PASSIVE);`).
  5. *Integrity Verification*: Periodic background `PRAGMA quick_check;`.
  6. *Disaster Recovery*: Point-in-time backup restoration.
- **Mandatory 6B Condition**: Explicit distinction between routine WAL checkpoints and corruption/recovery procedures.

---

### 6A-09: Production Security & Multi-Layer SSRF Defense
- **Crawler Security Gateway**:
  1. **Scheme Validation**: Whitelist `http` and `https` only.
  2. **DNS Resolution & Address Pinning**: Resolve all IPv4/IPv6 addresses before connect.
  3. **CIDR Deny Matrix**:
     - `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (Private RFC 1918)
     - `127.0.0.0/8`, `::1` (Loopback)
     - `169.254.0.0/16`, `fe80::/10` (Link-Local / Cloud Metadata: AWS/GCP/Azure)
     - `0.0.0.0/8`, `100.64.0.0/10`, `198.18.0.0/15`
  4. **Redirect Defense**: Inspect each hop in redirect chains independently against DNS/IP deny lists.
  5. **Payload Limits & Sanitization**: Strict HTTP body size caps (e.g., max 10MB) and HTML sanitization.
- **Mandatory 6B Condition**: Zero direct unpinned `requests.get()` / `aiohttp.get()` in zombie workers; all outbound traffic routes through the SSRF security gateway.

---

### 6A-10: Phase 5 Invariant Preservation & Zero Direct Zombie Persistence
- **Strict Ingestion Invariant**:
  $$\text{Zombie Swarm} \longrightarrow \text{SourceObservation} \longrightarrow \text{Queue} \longrightarrow \text{CanonicalPipelineRunner (S01–S11)} \longrightarrow \text{Repositories} \longrightarrow \text{SqliteEngine}$$
- **Prohibition**: **Zombies must NEVER write directly to SQLite or bypass the pipeline.**
- **Mandatory 6B Condition**: Permanent boundary invariant in `test_architecture_boundaries.py` enforcing that no crawler or zombie module imports `src.storage` or opens database connections.

---

## 3. Approved Subphase Roadmap

```text
Phase 6: Internet-Scale Acquisition, Search, Security & Production Operations
├── Gate 6A: Architecture Blueprint & Topology Review (APPROVED WITH CONDITIONS ✅)
├── Gate 6B: Scalable Zombie Swarm & Polite Ingestion (Partitions, SSRF Defense, Leases)
├── Gate 6C: SQLite FTS5 Full-Text Search Integration (Ranked BM25 & Snippets)
├── Gate 6D: Production Security, Authentication Middleware & Rate Limiting
├── Gate 6E: Observability, Metrics & Telemetry Dashboard (/metrics, OpenTelemetry)
└── Gate 6F: End-to-End Scale Verification & Final Phase 6 Closeout
```

---

## 4. Gate 6A Status & Authorization

**Gate 6A Status**: **APPROVED WITH CONDITIONS ✅**  
**Authorized for**: **Subphase 6B Implementation Plan & Execution**.
