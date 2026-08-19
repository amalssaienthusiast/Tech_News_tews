# Migration Inventory & Pre-Migration Audit

**Source Repository**: `/Users/sci_coderamalamicia/PROJECTS/Tech_News_Scrapper`  
**Source HEAD Commit**: `aa276d1a3d7ffb78f522a0c8da364e39cc055b71`  
**Target Repository**: `https://github.com/amalssaienthusiast/Tech_News_tews.git` (Local: `/Users/sci_coderamalamicia/PROJECTS/Tech_News_tews`)  
**Date**: `2026-08-19`  
**Role**: Principal Software Architect and Release Engineer  

---

## 1. Executive Summary

This inventory audits all components of `Tech_News_Scrapper` prior to establishing the new canonical production generation repository `Tech_News_tews`. The migration preserves all hardened engineering baselines (S01–S11 ingestion pipeline, Phase 5 architecture, Phase 6 security policies, Phase 8A-8H deployment & acceptance contracts, and operational reliability framework) while strictly excluding temporary databases, caches, compiled binaries, intermediate run data, and potential secrets.

---

## 2. Directory Breakdown & Source Lines of Code (LOC)

| Directory / Area | Category | Description | Migration Action | Files | Approx LOC |
|---|---|---|---|---|---|
| `src/` | Production Source | Canonical core, pipeline (S01-S11), API gateway, worker, zombies, security, storage, intelligence | **MIGRATE** (exclude `target/`, `__pycache__`, `.egg-info`) | ~180 | ~61,200 |
| `tests/` | Test Suites | Complete test suite (739 tests across security, API, pipeline, storage, deployment) | **MIGRATE** (exclude `__pycache__`) | 92 | 19,764 |
| `benchmarks/` | Benchmarks | Performance, throughput, deduplication, and pipeline benchmarks | **MIGRATE** | 20 | 7,689 |
| `experiments/` | Experiment Framework | Operational reliability framework (`configs/`, `runners/`, `collectors/`, `analysis/`, `scripts/`, `schemas/`) | **MIGRATE Framework** (preserve `runs/.gitkeep`, exclude raw run data) | ~25 | ~7,500 |
| `deploy/` | Deployment | Deployment manifests (`prometheus.yml`, etc.) | **MIGRATE** | 1 | 12 |
| `docs/` | Documentation | Architecture specifications, canonical runtime, phase completion reports, audits | **MIGRATE** | 121 | 14,453 |
| `config/` | Configuration | Production & environment settings (`settings.py`, `config.py`, `sources.json`) | **MIGRATE** | 8 | 675 |
| `scripts/` | Tooling & Automation | Operational scripts, background launchers, system maintenance | **MIGRATE** | 7 | 789 |
| `misc/` | Test Fixtures | Deterministic offline parser HTML fixtures (`techcrunch_sample.html`, etc.) | **MIGRATE** | 3 | 2,023 |
| `gui_qt/` | Visualization Client | Standalone PyQt6 desktop visualization tool | **MIGRATE** (exclude `cache/`, `*.sqlite`) | ~25 | ~6,500 |
| Root Core | Build & Deployment | `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `requirements*.txt`, `Makefile`, `LICENSE`, `README.md`, `.gitignore`, `.dockerignore`, `.env.example`, `.env.production.example` | **MIGRATE & ENHANCE** | 14 | ~4,200 |

---

## 3. Excluded Artifacts Policy

The following items are strictly **EXCLUDED** from the new production repository:

1. **Git Metadata**: `.git/` (New clean git lineage initialized on `main` branch).
2. **Compiled Bytecode & Caches**: `__pycache__/`, `.pytest_cache/`, `*.pyc`, `*.pyo`, `*.egg-info/`.
3. **Rust Build Outputs**: `src/bypass/target/` (rebuilt via cargo/maturin during build).
4. **Runtime & Temporary Databases**: `*.db`, `*.sqlite`, `*.sqlite3`, `*.sqlite-wal`, `*.sqlite-shm` (`live_feed.db`, `data/*.db`, `cache/*.sqlite`, `gui_qt/cache/*.sqlite`).
5. **Raw Experiment Run Data**: `experiments/operational_reliability/runs/*` (preserved `.gitkeep` only).
6. **Local Secret / Environment Overrides**: `.env` (template preserved in `.env.example` and `.env.production.example`).
7. **Ad-hoc Scratch / Dump Files**: `Tech_News_Scrapper.zip`, `ddg_html.html`, `classes.txt`, `dataclasses.txt`, `massive_list.txt`, `cli_output.txt`, `.DS_Store`.

---

## 4. Security Audit & Pre-Flight Findings

- **Secret Scan**: Scanned repository for `.pem`, `.key`, private keys, API credentials, Telegram tokens, and AWS secrets.
- **Result**: 0 plaintext secrets committed in code. All configuration uses environment variable interpolation (`os.getenv(...)`) with fail-closed security policies in production mode (`TECHNEWS_ENV=production`).
- **Templates**: `.env.example` and `.env.production.example` contain clean placeholders only.

---

## 5. Migration Execution Strategy

1. Target directory: `/Users/sci_coderamalamicia/PROJECTS/Tech_News_tews`
2. Initialize fresh Git repository on branch `main`.
3. Copy audited source, test, doc, config, script, and manifest trees.
4. Establish clean `.gitignore` and `.dockerignore`.
5. Author comprehensive production `README.md` and `docs/HISTORICAL_BASELINE.md`.
6. Compile all Python modules (`compileall`) and execute full verification test suites.
7. Commit initial baseline commit: `"bootstrap: establish canonical production-generation baseline"`.
