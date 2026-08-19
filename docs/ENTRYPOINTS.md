# Executable Entrypoints & Process Inventory

**Document Status**: Phase 0 Baseline  
**Scope**: All CLI scripts, server processes, desktop launchers, and background workers in the repository.

---

## 1. Primary Production Entrypoints

### 1.1 `main_engine.py` (Central Aggregation & Streaming Engine)
- **Role**: Primary headless server process that orchestrates ingestion, clustering, and streaming delivery.
- **Protocol**: HTTP REST + Server-Sent Events (SSE) via `aiohttp.web`.
- **Default Network Binding**: `http://0.0.0.0:8080` (Configurable via `--host`, `--port`, `ENGINE_PORT`, `ENGINE_HOST`).
- **CLI Arguments**:
  - `--port INT` (Default: `8080` / `os.getenv("ENGINE_PORT")`)
  - `--host STR` (Default: `0.0.0.0` / `os.getenv("ENGINE_HOST")`)
  - `--concurrency INT` (Default: `2` workers)
  - `--buffer-size INT` (Default: `5000` articles in ring buffer)
  - `--discovery-interval INT` (Default: `120` seconds)
- **Endpoints Exposed**:
  - `GET /api/v1/health` — JSON health and engine uptime statistics
  - `GET /api/v1/feed?since=<iso>&limit=100&pipeline=breaking` — Batch article polling
  - `GET /api/v1/sources` — List of registered source descriptors
  - `GET /api/v1/stream` — Real-time Server-Sent Events (SSE) push stream
- **Security Posture**: Currently lacks API key authentication and uses wildcard CORS (`Access-Control-Allow-Origin: *`). Scheduled for unification in Phase 1.

---

### 1.2 `main.py` (FastAPI Server & Multi-Mode Orchestrator)
- **Role**: Standard API application server, database initializer, and test runner.
- **Protocol**: HTTP REST + WebSockets via FastAPI / Uvicorn.
- **Default Network Binding**: `http://0.0.0.0:8000`.
- **CLI Commands & Subcommands**:
  - `python main.py run` — Interactive terminal news viewer
  - `python main.py search <query>` — Search articles by keyword
  - `python main.py sources` — List active scraper sources
  - `python main.py test` — Run internal diagnostic checks
  - `python main.py --mode api` / `main:run_api` — Launch FastAPI server (`src.api.app:app`) via Uvicorn
  - `python main.py --mode worker` — Run background scheduler worker
- **Endpoints Exposed** (via `src/api/app.py`):
  - `GET /health`, `GET /health/detailed`, `GET /metrics` (Prometheus)
  - `GET /`, `GET /feed/latest`, `GET /sources`, `WS /feed/ws`
  - `POST /admin/api-keys` (Pro tier only)

---

### 1.3 `telegram_feeder_bot.py` (Telegram Broadcast Delivery Bot)
- **Role**: Automated delivery client that subscribes to the engine's SSE stream / batch feed and posts formatted breaking news to Telegram channels.
- **Runtime Environment**: Async background process.
- **CLI Arguments**:
  - `--engine-url STR` (Default: `http://localhost:8080` / `os.getenv("ENGINE_API_URL")`)
  - `--test` — Sends a test message to verify Telegram channel permissions and exits
  - `--dry-run` — Runs polling without dispatching network calls to Telegram API
  - `--channel STR` — Overrides target Telegram channel username/ID
- **Required Secrets**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

---

### 1.4 `cli.py` (Developer & Operator Command Line Interface)
- **Role**: Operational management tool for scraping, database inspection, cache management, and AI debugging.
- **CLI Commands**:
  - `technews crawl <url>` — On-demand single URL scrape through bypass ladder
  - `technews search <query>` — Full-text article search
  - `technews stats` — Database and cache statistics
  - `technews export --format json|csv` — Export aggregated articles
  - `technews sources list|enable|disable` — Source administration
  - `technews db migrate|vacuum|clean` — Database maintenance

---

### 1.5 `run_qt.py` (Desktop GUI Launcher)
- **Role**: Desktop user interface launcher for graphical monitoring, live feed viewing, and visual source inspection.
- **Framework**: PyQt6 / PySide6 (`gui_qt.app_qt_migrated`).
- **Execution**: Desktop-only (fails gracefully in headless Linux/Pi environments when `$DISPLAY` is absent).

---

## 2. Secondary & Legacy Entrypoints

| File | Status | Action Needed | Notes |
|:---|:---:|:---:|:---|
| `src/api/main.py` | `DEAD` | `DELETE` | Legacy duplicate FastAPI entry point. Features already ported to `src/api/app.py`. |
| `scripts/deploy_resilience.py` | `ACTIVE` | `REFACTOR` | Resilience deployment diagnostic script. |
| `scripts/migrate_db.py` | `ACTIVE` | `KEEP` | SQLite to PostgreSQL migration runner. |
| `scripts/setup_autostart.sh` | `ACTIVE` | `REFACTOR` | Raspberry Pi systemd autostart setup script. Update service paths and remove hardcoded secrets. |
| `scripts/services.sh` | `ACTIVE` | `KEEP` | Systemd service management helper (`status`, `logs`, `restart`, `stop`). |

---

## 3. Entrypoint Consolidation Target

Following Phase 1 & Phase 2 consolidation, the canonical entrypoints will be strictly:

```text
1. Engine Server:    main_engine.py (Headless central aggregation & streaming)
2. API Gateway:      src/api/app.py (Authenticated public/private REST & WS)
3. Delivery Bot:     telegram_feeder_bot.py (Telegram broadcast consumer)
4. CLI Utility:      cli.py (Console operator commands & diagnostics)
5. Desktop UI:       run_qt.py (Isolated desktop GUI client)
```
