# Working Tree Status & Baseline Inventory

**Date of Audit**: 2026-08-13
**Repository**: `Tech_News_Scrapper`
**Target Environment**: Production Server / Headless Raspberry Pi Zero 2W / Docker Container

---

## 1. Git Working Tree Status

- **Branch**: `main`
- **Working Tree State**: Uncommitted ZIP backup file `Tech_News_Scrapper.zip` present.
- **Untracked / Scratch Artifacts**:
  - `Tech_News_Scrapper.zip` (1.05 MB archive)
  - `classes.txt`, `dataclasses.txt`, `massive_list.txt`, `cli_output.txt`, `ddg_html.html`
  - Local database files: `live_feed.db` (16 KB)
  - Cache directory: `cache/` (dedup SQLite state, bypass cache)

---

## 2. Codebase Metrics Summary

| Category | Count / Value | Notes |
|:---|:---|:---|
| **Total Files** | 334 | Across repository root, `src/`, `gui_qt/`, `tests/`, `config/`, `scripts/` |
| **Python Files** | 293 | Excluding virtual environments (`env/`, `.venv/`) |
| **Total Python Lines** | 87,784 | 54,276 lines in `src/`, 23,278 lines in `gui_qt/`, 6,475 lines in `tests/` |
| **Test Files** | 45 | 39 unit/integration test modules, benchmark scripts, manual test helpers |
| **Top-Level Entry Points** | 5 | `main_engine.py`, `main.py`, `cli.py`, `telegram_feeder_bot.py`, `run_qt.py` |
| **Source Subpackages** | 34 | Under `src/` directory |

### Code Distribution by Top-Level Directory

| Directory | Files | Python Lines | Primary Responsibility |
|:---|:---:|:---:|:---|
| `src/` | 183 | 54,276 | Core engine, ingestion, zombies, bypass, clustering, persistence, API |
| `gui_qt/` | 53 | 23,278 | Desktop GUI application (PyQt6 / PySide6 migrated panels, widgets, dialogs) |
| `tests/` | 45 | 6,475 | Test suites (unit, integration, bypass, database, performance) |
| `config/` | 3 | 401 | Configuration loader, settings schema, YAML parsers |
| `scripts/` | 2 | 405 | Deployment, resilience verification, database migration helpers |
| `api/` | 2 | 162 | Root-level API module (duplicate/legacy event route) |
| Root `.py` files | 5 | 2,787 | Main entry points (`main_engine.py`, `telegram_feeder_bot.py`, etc.) |

---

## 3. Dependency & Packaging Inventory

### Package Files Present
1. `pyproject.toml` (3,605 bytes): Tooling configuration only (Ruff, Pytest, Coverage, Mypy, Black). **Explicitly lacks a `[project]` build table** — the project cannot currently be installed via `pip install -e .`.
2. `requirements.txt` (4,579 bytes): Comprehensive monolithic dependency list.
3. `requirements-dev.txt` (380 bytes): Testing and linting tooling (`pytest`, `ruff`, `mypy`, `coverage`).
4. `requirements-pi.txt` (464 bytes): Lightweight dependency profile tailored for resource-constrained Raspberry Pi Zero 2W.
5. `requirements-constraints.txt` (1,488 bytes): Pinned dependency constraint definitions.

---

## 4. Subpackage Line Count Breakdown (`src/`)

```text
src/
├── engine/             22 files | 10,674 lines  (Unified chain, dedup, quality, scheduler, breakers)
├── bypass/             14 files |  6,823 lines  (5-tier bypass escalation ladder, stealth, primp)
├── sources/            11 files |  4,089 lines  (Source adapters, Google News, Bing, RSS feeds)
├── intelligence/        7 files |  3,034 lines  (AI summarizer, LLM processor, clustering)
├── db_storage/          6 files |  2,471 lines  (AsyncDatabase, db_handler, ephemeral store, unified storage)
├── data_structures/     6 files |  2,185 lines  (Ring buffer, priority queues, trees)
├── events/              8 files |  2,020 lines  (Event Brain, clustering, confidence, freshness)
├── api/                 8 files |  1,614 lines  (FastAPI app, routes, auth, rate limiting)
├── newsletter/          8 files |  1,474 lines  (Beehiiv, email formatting, dispatch)
├── crawler/             4 files |  1,405 lines  (Deep web crawler, crawler manager)
├── resilience/          5 files |  1,172 lines  (Auto-fixer, deprecation manager, source health)
├── core/                5 files |  1,149 lines  (Domain models, types, exceptions, interfaces)
├── monitoring/          4 files |  1,092 lines  (Prometheus metrics, health check probes)
├── realtime/            3 files |  1,033 lines  (WebSocket server, SSE broadcaster)
├── zombies/            10 files |  1,022 lines  (ZombieSwarm, species: RSS, GitHub, Hacker, Web, Sec)
├── search/              4 files |    880 lines  (Elasticsearch / SQLite full-text search)
├── compliance/          3 files |    819 lines  (Robots.txt parser, rate limiter compliance)
├── extraction/          5 files |    812 lines  (Readability, boilerpipe, metadata extractor)
├── user/                2 files |    766 lines  (User preferences, profile management)
├── processing/          2 files |    742 lines  (Text cleaning, sanitization)
├── compatibility/       3 files |    684 lines  (Package shim, RSS adapter legacy wrappers)
├── operations/          2 files |    640 lines  (Diagnostic toolkit, system inspect)
├── infrastructure/      2 files |    618 lines  (Docker helpers, host probes)
├── queue/               3 files |    543 lines  (Celery worker configuration, task queue)
├── notifications/       2 files |    524 lines  (Slack, Discord, Email dispatchers)
├── performance/         3 files |    489 lines  (Parallel scraper, benchmarking)
├── cache/               2 files |    485 lines  (Disk/memory cache wrappers)
├── utils/               5 files |    379 lines  (HTTP helpers, thumbnail fetcher)
├── scrapers/            6 files |    358 lines  (Legacy scraper factory, base scrapers)
├── personalization/     2 files |    347 lines  (Topic recommendation models)
├── discovery/           2 files |    325 lines  (Discovery aggregator)
├── feed_generator/      3 files |    228 lines  (RSS / Atom / JSON feed builder)
├── security/            2 files |    214 lines  (API key hashing, encryption helpers)
└── scheduler/           2 files |     46 lines  (Legacy cron/task scheduler)
```

---

## 5. Active Execution Modes

1. **Headless Engine Mode**: `main_engine.py` — runs `ZombieSwarm` + `BreakingNewsScanner` + `EnhancedNewsPipeline` + aiohttp HTTP/SSE server on port `8080`.
2. **Standard API Server Mode**: `main.py --mode api` — launches FastAPI application (`src/api/app.py`) on port `8000`.
3. **Telegram Consumer Mode**: `telegram_feeder_bot.py` — polls engine API via SSE or HTTP batch endpoint and pushes breaking updates to Telegram channel `@tewsavailable`.
4. **Desktop GUI Mode**: `run_qt.py` — launches PyQt6 desktop interface (`gui_qt/app_qt_migrated.py`).
5. **CLI Utility Mode**: `cli.py` — CLI tool for manual scraping, diagnostics, feed generation, and database inspection.
