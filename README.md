# Tech News Platform (`Tech_News_tews`)

An enterprise-grade, high-throughput technology news aggregation, deduplication, real-time event clustering, and intelligence platform built in Python with SQLite WAL persistence, multi-species autonomous scrapers, and a hardened production container runtime.

---

## 1. Overview

`Tech_News_tews` continuously monitors hundreds of heterogeneous technical sources (RSS feeds, Hacker News, GitHub releases, security advisories, engineering blogs), normalizes noisy HTML content, eliminates duplicate stories across outlets, clusters related coverage into unified tech events with evolving timelines, and exposes authenticated query APIs and real-time event streams.

---

## 2. Architecture & Topology

```text
                                  ┌────────────────────────┐
                                  │   Target Web Sources   │
                                  │ (RSS, HN, GitHub, CVE) │
                                  └───────────┬────────────┘
                                              │
                                              ▼
                                 ┌─────────────────────────┐
                                 │ Autonomous Zombie Swarm │
                                 │   (src/zombies/swarm)   │
                                 └────────────┬────────────┘
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          CANONICAL INGESTION PIPELINE (S01–S11)                        │
│                                                                                        │
│  S01: Normalizer        → S02: Freshness Evaluator → S03: Relevance Filter             │
│  S04: Quality Gate      → S05: Title Dedup         → S06: Content Fingerprint          │
│  S07: Event Clusterer   → S08: Entity Extractor    → S09: Summary Generator            │
│  S10: Persistence       → S11: Publication Bus                                         │
└─────────────────────────────────────────────┬──────────────────────────────────────────┘
                                              │
                       ┌──────────────────────┴──────────────────────┐
                       ▼                                             ▼
         ┌───────────────────────────┐                 ┌───────────────────────────┐
         │  SQLite WAL Storage Engine│                 │    FastAPI API Gateway    │
         │  (/data/canonical_*.db)   │                 │    (uvicorn: port 8000)   │
         └───────────────────────────┘                 └───────────────────────────┘
```

The production platform runs as a coordinated multi-container topology:
- **`technews_api`**: FastAPI gateway exposing `/v1/articles`, `/v1/events`, `/sources`, `/health`, and `/metrics` on port 8000.
- **`technews_worker`**: Single-process canonical ingestion daemon executing `src.worker`, coordinating `ZombieSwarm` acquisition and the S01–S11 pipeline.
- **`technews_prometheus`**: Time-series metrics collection scraping container and application telemetry.

---

## 3. Canonical Ingestion Pipeline (S01–S11)

Every discovered observation passes through an immutable, strictly partitioned pipeline:

| Stage | Name | Description |
|---|---|---|
| **S01** | `Normalizer` | Sanitizes HTML, normalizes canonical URLs, trims titles, and constructs `NormalizedArticle`. |
| **S02** | `FreshnessEvaluator` | Computes temporal decay scoring and flags stale observations. |
| **S03** | `RelevanceFilter` | Matches domain taxonomy, keywords, and technical density. |
| **S04** | `QualityGate` | Filters low-effort aggregations, link farms, and empty payloads. |
| **S05** | `DedupEvaluator` | Performs exact URL matching, SimHash fingerprinting, and sliding-window deduplication. |
| **S06** | `ContentFingerprint` | Computes robust MinHash / TLSH fuzzy content hashes. |
| **S07** | `EventClusterer` | Clusters corroborating coverage into unified `TechEvent` aggregates using title 3-shingles, Jaccard similarity ($\ge 0.55$), and 48-hour sliding temporal windows. |
| **S08** | `EntityExtractor` | Extracts verified organizations, technologies, and CVE identifiers. |
| **S09** | `SummaryGenerator` | Generates concise multi-source summaries. |
| **S10** | `PersistenceStage` | Persists articles, events, and timeline entries into SQLite WAL repositories. |
| **S11** | `PublicationBus` | Emits real-time event updates to SSE consumers and webhook dispatchers. |

---

## 4. Security & Compliance Model

- **Fail-Closed Authentication**: In production mode (`TECHNEWS_ENV=production`), all data endpoints require valid `X-API-Key` headers (Role-Based Access Control: `ADMIN`, `READ_WRITE`, `READ_ONLY`). Unauthenticated or invalid requests fail closed with HTTP 401.
- **SSRF Protection (`AcquisitionPolicy`)**: All outbound HTTP and browser acquisitions validate destination IP addresses, strictly blocking RFC 1918 private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), AWS metadata endpoints (`169.254.169.254`), and loopbacks (`127.0.0.1`, `::1`).
- **Strict TLS Verification**: All scrapers enforce certificate validation by default.
- **Non-Root Execution**: Container images execute under unprivileged `nobody:nogroup` (UID 65534) users.

---

## 5. Storage Architecture (SQLite WAL)

- **Engine**: SQLite 3 with Write-Ahead Logging (`PRAGMA journal_mode=WAL;`).
- **Synchronous Mode**: `PRAGMA synchronous=NORMAL;` with `PRAGMA foreign_keys=ON;`.
- **Concurrency**: Thread-safe connection pooling with busy timeout handlers, supporting 100+ concurrent reads alongside batch transactional writes.
- **Search**: Full-text search powered by SQLite FTS5 extension.

---

## 6. Development & Quick Start

### Prerequisites
- Python 3.12+
- SQLite 3.40+
- (Optional) Docker & Docker Compose v2 for containerized workflows
- (Optional) Playwright for JavaScript-rendered scraping

### Local Setup
```bash
# 1. Clone repository
git clone https://github.com/amalssaienthusiast/Tech_News_tews.git
cd Tech_News_tews

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# 4. Copy environment configuration template
cp .env.example .env

# 5. Run test suite
pytest -v
```

---

## 7. Production Deployment (Docker Compose)

The production stack is defined in [`docker-compose.yml`](docker-compose.yml):

```bash
# 1. Configure production environment
cp .env.production.example .env
# Edit .env to set your TECHNEWS_ADMIN_API_KEY, TECHNEWS_RW_API_KEY, TECHNEWS_RO_API_KEY

# 2. Build production images from scratch
docker compose build --no-cache

# 3. Start stack in background
docker compose up -d

# 4. Verify API health
curl -f http://localhost:8000/health
```

---

## 8. Operational Reliability & Cloud Experiments

The repository includes a self-contained operational reliability framework under `experiments/operational_reliability/`:
- **Run Harness**: `bash experiments/operational_reliability/scripts/run.sh --regime E1`
- **SLO Analysis**: `bash experiments/operational_reliability/scripts/analyze.sh --latest`
- **Supported Soak Regimes**:
  - `E1`: 1-Hour Calibration Soak (40 items/s base, 500 items/s burst, lease takeover, 429 backpressure)
  - `E2`: 6-Hour Endurance Soak
  - `E3`: 24-Hour Stability Soak

---

## 9. Repository Status & Feature Matrix

| Subsystem / Feature | Implementation Status | Verification Level |
|---|---|---|
| S01–S11 Ingestion Pipeline | **IMPLEMENTED** | 🟢 **VERIFIED** (65/65 unit & stage tests passing) |
| FastAPI Gateway (`src/api/app.py`) | **IMPLEMENTED** | 🟢 **VERIFIED** (Fail-closed RBAC, 40/40 tests passing) |
| Autonomous Zombie Swarm | **IMPLEMENTED** | 🟢 **VERIFIED** (Multi-species scrapers, rate-limit state machine) |
| SQLite WAL Storage Engine | **IMPLEMENTED** | 🟢 **VERIFIED** (Zero FK violations, concurrency validated) |
| SSRF Guard & TLS Enforcement | **IMPLEMENTED** | 🟢 **VERIFIED** (84/84 security regression tests passing) |
| Docker Multi-Stage Runtime | **IMPLEMENTED** | 🟢 **VERIFIED** (Gate 8E-H4 Clean-Host Acceptance passed) |
| Playwright Headless Browser | **IMPLEMENTED** | 🟢 **VERIFIED** (Chromium v143.0 lifecycle validated) |
| Cloud E1 1-Hour Ingestion Soak | **IMPLEMENTED** | 🟡 **PLANNED** (Ready for cloud VM execution) |
| Desktop Qt Visualization Client | **IMPLEMENTED** | 🔴 **DEFERRED (P3)** (`gui_qt` modularization backlog) |
| Raspberry Pi 4/5 Deployment | **IMPLEMENTED** | 🟡 **PLANNED** (Lightweight runtime profiles in `deploy/`) |

---

## 10. License

Copyright (c) 2026 amalssaienthusiast. All Rights Reserved.

This repository and all of its contents are proprietary and confidential. Permission is granted to view the source code for educational and informational purposes only — see the [`LICENSE`](LICENSE) file for complete terms and restrictions.
