# Historical Baseline & Repository Provenance

**New Repository**: `Tech_News_tews` (`https://github.com/amalssaienthusiast/Tech_News_tews.git`)  
**Historical Source Repository**: `Tech_News_Scrapper`  
**Migration Date**: `2026-08-19`  
**Source HEAD Commit SHA**: `aa276d1a3d7ffb78f522a0c8da364e39cc055b71` (`aa276d1`)  
**Status**: 🟢 Canonical Production Lineage Established  

---

## 1. Context & Purpose of Migration

This repository (`Tech_News_tews`) represents the clean, hardened, production generation of the Tech News Ingestion & Intelligence Platform, branched off from the historical development repository (`Tech_News_Scrapper`).

The historical repository served as the initial exploratory and iterative research codebase. Over multiple major engineering phases (Phases 0 through 8H), the architecture was progressively hardened, transitioning from legacy ad-hoc scripts to an authoritative, enterprise-grade runtime architecture centered around:
- The **S01–S11 Canonical Ingestion Pipeline**
- The **FastAPI Production API Gateway** (`src/api/app.py`)
- The **Autonomous Multi-Species Zombie Swarm** (`src/zombies/`)
- High-concurrency **SQLite WAL** persistence
- Containerized Docker deployment topology (`api`, `worker`, `prometheus`)
- Comprehensive empirical validation, security policies (SSRF, TLS, RBAC), and operational reliability frameworks.

To establish a clean, independent Git history free from legacy development bloat (such as historical compiler caches, intermediate test database dumps, and abandoned prototypes), this new repository is initialized as the authoritative lineage for all future production development.

---

## 2. Completed Milestones & Architectural Baseline

The migrated baseline includes all engineering achievements through commit `aa276d1`:

1. **Phase 0–4: Autonomous Acquisition & Swarm Architecture**:
   - SQLite-backed distributed `ZombieCoordinator` and species-specific scrapers (`z_rss`, `z_github`, `z_hacker`, `z_security`, `z_web`).
   - Anti-bot bypass client, smart proxy router, stealth headless browser lifecycle.
2. **Phase 5: Canonical Pipeline (S01–S11)**:
   - Formally partitioned, immutable stage contracts from S01 (Normalization) to S11 (Publication Bus).
   - Jaccard title shingling and entity-overlap event clustering (S07) with sliding temporal window invariants.
3. **Phase 6: Security, Search & Observability**:
   - Fail-closed SSRF protection blocking RFC 1918, RFC 4193, AWS metadata (`169.254.169.254`), and loopbacks.
   - Strict TLS verification across all acquisition agents.
   - Fail-closed RBAC API authentication (`TECHNEWS_ENV=production`) with ephemeral token validation.
   - Prometheus metrics exposition.
4. **Phase 7: Empirical Calibration**:
   - Comprehensive benchmarks across throughput, deduplication latency, and storage concurrency.
5. **Phase 8A–8H: Hardened Runtime, Isolation & Acceptance**:
   - Deprecation and isolation of legacy monolith entrypoints (`main_engine.py`, `src/api/main.py`).
   - Containerized production deployment contract (`Dockerfile`, `docker-compose.yml`) targeting canonical port 8000 and `/health`.
   - Remediation of all independently verified P1/P2 audit defects (Audit Date: 2026-08-19).
   - Gate 8E-H4 Clean-Host Runtime Acceptance verification.

---

## 3. Excluded Artifacts

In accordance with production repository hygiene standards, the following artifacts from the historical repository were intentionally **NOT** migrated:
- Historical Git commit objects (`.git/`)
- Compiled Python bytecode (`__pycache__/`, `.pytest_cache/`, `*.pyc`)
- Rust build compiler targets (`src/bypass/target/`)
- Runtime SQLite database instances (`live_feed.db`, `data/*.db`, `cache/*.sqlite`)
- Raw experiment run logs (`experiments/operational_reliability/runs/*`)
- Temporary archives, zip files, and ad-hoc scratch text dumps (`Tech_News_Scrapper.zip`, `ddg_html.html`, `massive_list*.txt`, `classes.txt`)
- Local `.env` files (clean templates preserved in `.env.example` and `.env.production.example`).

---

## 4. Relationship to Historical Repository

- The historical repository (`Tech_News_Scrapper`) is preserved as a static historical record.
- No history was rewritten or destroyed in the old repository.
- All new features, bug fixes, operational reliability soaks (Cloud E1–E6), and production releases will occur exclusively within `Tech_News_tews`.
