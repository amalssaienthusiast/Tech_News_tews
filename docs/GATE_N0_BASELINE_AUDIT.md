# Gate N0: Canonical New-Repository Baseline Audit

**Repository**: `Tech_News_tews` (`https://github.com/amalssaienthusiast/Tech_News_tews.git`)  
**Branch**: `main`  
**Audited Commit SHA**: `7893b4a001d31ff170b12aaa28917e575242fd60` (`7893b4a`)  
**Remote Sync**: `HEAD == origin/main` (Verified)  
**Audit Date**: `2026-08-19`  
**Role**: Principal Software Architect and Release Engineer  
**Gate Status**: 🟡 **N0 CONDITIONAL PASS — REQUIRES LICENSE ALIGNMENT BEFORE CLOUD SOAK**  

---

## 1. Executive Summary

This report establishes the baseline audit of the canonical production repository **`Tech_News_tews`** following migration from `Tech_News_Scrapper`.

All technical production baselines (S01–S11 pipeline, FastAPI gateway, autonomous zombie swarm, SQLite WAL persistence, fail-closed RBAC, SSRF guards, Playwright headless browser, and operational reliability framework) were independently verified functional with **736/739 (99.6%) passing tests**, zero compilation errors, zero leaked secrets, and zero tracked temporary databases.

A single formal discrepancy was identified: `LICENSE` contains a custom proprietary/educational reservation while `README.md` and `pyproject.toml` declare `MIT`.

---

## 2. Git Provenance & Remote Sync

- **Local HEAD**: `7893b4a001d31ff170b12aaa28917e575242fd60`
- **Remote Origin**: `https://github.com/amalssaienthusiast/Tech_News_tews.git`
- **Tracking Branch**: `main` $	o$ `origin/main` (In exact agreement)
- **Working Tree**: Completely clean (`git status --short` returns 0 modified files)

---

## 3. Repository Completeness & Generated Artifact Audit

### Verified Directory Trees & Manifests
- `src/` (Production core, S01–S11 pipeline, API gateway, zombies, storage, security)
- `tests/` (739 test cases)
- `benchmarks/` (Ingestion, SimHash, and persistence benchmarks)
- `experiments/operational_reliability/` (Full framework with clean `runs/.gitkeep`)
- `deploy/`, `docs/`, `config/`, `scripts/`, `misc/`, `gui_qt/`
- `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `requirements*.txt`, `Makefile`, `LICENSE`, `README.md`, `.gitignore`, `.dockerignore`, `.env.example`, `.env.production.example`

### Generated Artifact Policy Enforcement (`git ls-files`)
- **Tracked SQLite Databases**: `0` (Zero `*.db`, `*.sqlite`, `*.sqlite3` tracked)
- **Tracked Bytecode / Cache**: `0` (Zero `__pycache__`, `.pytest_cache`, `*.pyc` tracked)
- **Tracked Rust Targets**: `0` (Zero `src/bypass/target/` artifacts tracked)
- **Tracked Raw Soak Logs**: `0` (`experiments/operational_reliability/runs/*` excluded)
- **Tracked Local Secrets**: `0` (Zero `.env` or `.env.local` tracked)

---

## 4. Security & Secret Audit

- **Automated Security Scan**: Scanned 598 tracked files for private keys, AWS tokens, GitHub credentials, Telegram tokens, and hardcoded passwords.
- **Result**: `0` plaintext secrets or leaked keys.
- **Fail-Closed Security Model**:
  - `TECHNEWS_ENV=production` strictly enforces API key authentication.
  - SSRF guard actively blocks RFC 1918, RFC 4193, AWS metadata (`169.254.169.254`), and loopback addresses.

---

## 5. License Consistency Audit (BLOCKER / P0 Finding)

- **`LICENSE` File Content**:
  > "Copyright (c) 2026 amalssaienthusiast. All Rights Reserved. This repository and all of its contents are proprietary and confidential. Permission is granted to view the source code for educational and informational purposes only..."
- **`pyproject.toml` Line 11**: `license = { text = "MIT" }`
- **`README.md` Section 10**: `This project is licensed under the MIT License...`
- **Classification**: 🔴 **BLOCKING BASELINE INCONSISTENCY (P0)**.
- **Action Required**: The project owner must explicitly specify whether the canonical license is **Proprietary (View-Only)** or **Open-Source (MIT)** so that `LICENSE`, `pyproject.toml`, and `README.md` are aligned.

---

## 6. Test Inventory & Compilation Audit

```text
================================ TEST MATRIX ================================
Total Tests Collected:  739
Passing Tests:          736 (99.6%)
Failing Tests:            3 (0.4% — Isolated to tests/test_gui_qt.py)
Skipped / Errors:         0
Compilation Status:     0 Errors (python3 -m compileall -q src tests benchmarks experiments)
Git Diff Integrity:     0 Formatting / Whitespace Errors
```

### Exact Failing Tests (3 tests — Classified as Deferred P3)
1. `tests/test_gui_qt.py::TestImports::test_main_window_import` (`ModuleNotFoundError: gui_qt.main_window`)
2. `tests/test_gui_qt.py::TestImports::test_controller_import` (`ModuleNotFoundError: gui_qt.controller`)
3. `tests/test_gui_qt.py::TestImports::test_package_import` (`ModuleNotFoundError: gui_qt.main_window`)

---

## 7. Static Docker & Runtime Invariants

| Component | Static Verification | Runtime Cloud Target Requirement |
|---|---|---|
| **Multi-Stage Dockerfile** | Validated (builder $	o$ `python:3.12-slim-bookworm`) | Docker Engine 24.0+ |
| **Non-Root Execution** | `USER nobody:nogroup` (UID 65534) | Linux Container Isolation |
| **API Entrypoint** | `uvicorn src.api.app:app --host 0.0.0.0 --port 8000` | Port 8000 bind |
| **Worker Entrypoint** | `python -m src.worker` | Shared `/data` volume |
| **Database Path** | `/data/canonical_technews.db` (WAL mode enabled) | SQLite 3.40+ |
| **Observability** | `prom/prometheus:v2.45.0` on port 9090 | Prometheus scraping |

---

## 8. Playwright & Browser Audit

- **Package**: `playwright` 1.57.0
- **Browser Binary**: Chromium `143.0.7499.4` (build v1200)
- **Lifecycle Test**: Headless browser launch, DOM construction, element location, and clean exit verified functional with 0 orphan processes.

---

## 9. Canonical Runtime & Ingestion Paths

- **`src.api.app:app`**: 🟢 **CANONICAL** Production API Gateway.
- **`src.worker`**: 🟢 **CANONICAL** Production Ingestion Worker daemon.
- **`UnifiedFeedChainEngine`**: 🟢 **CANONICAL** Ingestion orchestration connecting Swarm to S01–S11.
- **`ZombieSwarm`**: 🟢 **CANONICAL** Autonomous scraper acquisition swarm.
- **`main_engine.py`**: 🟡 **DEPRECATED** Historical monolith server (port 8080) isolated from Docker.
- **`src/api/main.py`**: 🟡 **DEPRECATED** Historical API with active deprecation warnings on import.
- **`cli.py` / `main.py` / `telegram_feeder_bot.py`**: 🔵 **COMPATIBILITY** Auxiliary CLI and broadcast clients.

---

## 10. Outbound Acquisition Security Data-Flow

| Acquisition Source | Acquisition Driver | Security Entrypoint | SSRF Enforcement | TLS Certificate Verification | Redirect & Size Safety | Security Status |
|---|---|---|---|---|---|---|
| **RSS Species** (`z_rss.py`) | `InternetBrowser` $	o$ `BypassResolver` | `_attempt_tier` | `SSRFGuard.validate_url` | Enforced (certifi) | Hop-by-Hop validated | 🟢 PROTECTED |
| **GitHub Species** (`z_github.py`) | `InternetBrowser` $	o$ `BypassResolver` | `_attempt_tier` | `SSRFGuard.validate_url` | Enforced (certifi) | Hop-by-Hop validated | 🟢 PROTECTED |
| **Hacker News** (`z_hacker.py`) | `InternetBrowser` $	o$ `BypassResolver` | `_attempt_tier` | `SSRFGuard.validate_url` | Enforced (certifi) | Hop-by-Hop validated | 🟢 PROTECTED |
| **Security Feeds** (`z_security.py`) | `InternetBrowser` $	o$ `BypassResolver` | `_attempt_tier` | `SSRFGuard.validate_url` | Enforced (certifi) | Hop-by-Hop validated | 🟢 PROTECTED |
| **Web Species** (`z_web.py`) | `InternetBrowser` $	o$ `BypassResolver` | `_attempt_tier` | `SSRFGuard.validate_url` | Enforced (certifi) | Hop-by-Hop validated | 🟢 PROTECTED |
| **Playwright Stealth** | Chromium Headless | `_attempt_tier` | `SSRFGuard.validate_url` | Browser TLS Context | Controlled Navigation | 🟢 PROTECTED |
| **Web Discovery Agent** | `requests.Session` / `aiohttp` | `WebDiscoveryAgent` | Ad-hoc Host Resolution | Standard CA | Client default | 🟡 P2 ENHANCEMENT |

---

## 11. Operational Reliability Framework Audit

- Framework located at `experiments/operational_reliability/`
- Local 5-second smoke run executed:
  - `RUN_MANIFEST.json` generated with full hardware and git fingerprint.
  - Telemetry recorded (`CPU`, `RSS`, `FDs`, `Database`).
  - Immutable SHA-256 checksums generated and verified.
  - `analyze.sh` offline SLO analyzer passed all criteria (0 silent loss, 0 SQLite busy errors, memory slope 1.71 MB/hr $\le$ 25 MB/hr).

---

## 12. Findings & Risk Classification

| ID | Severity | Category | Description | Recommendation |
|---|---|---|---|---|
| **N0-1** | 🔴 **P0 / BLOCKER** | Legal / Metadata | `LICENSE` is Proprietary View-Only while `pyproject.toml` and `README.md` state `MIT`. | Align `pyproject.toml` and `README.md` with the intended project license. |
| **N0-2** | 🟡 **P2** | Security Boundary | `src/discovery.py` uses direct HTTP sessions rather than `SafeHttpClient`. | Standardize discovery requests on `SafeHttpClient`. |
| **N0-3** | 🔵 **P3** | Test Backlog | `tests/test_gui_qt.py` fails 3 import tests due to pending GUI module split. | Modularize `gui_qt` into `main_window` and `controller` in GUI milestone. |
| **N0-4** | 🔵 **P3** | Deprecation | `tests/test_api_lifecycle.py` imports deprecated `src/api/main.py`. | Remove legacy import in Phase 9 cleanup. |

---

## 13. Baseline Freeze Recommendation

- **Technical Runtime Baseline**: 🟢 **VERIFIED & READY FOR FREEZE**.
- **Pre-requisite for Cloud E1 Launch**: Resolve Finding **N0-1** (License Alignment) to unblock public production deployment.
