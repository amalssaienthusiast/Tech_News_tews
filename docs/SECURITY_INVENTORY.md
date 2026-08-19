# Security Inventory & Vulnerability Assessment

**Document Status**: Phase 0 Baseline  
**Security Classification**: `P0 (Critical / Block Production)` | `P1 (High)` | `P2 (Medium)` | `P3 (Low)`

---

## 1. P0 Critical Vulnerabilities (Immediate Remediation Required)

### 1.1 Secret Exposure — Live Telegram Bot Token
- **Location 1**: `DEPLOYMENT_PI.md` (Lines 37 & 105)
- **Location 2**: `.env` (Line 6)
- **Compromised Secret**: `TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_BOT_TOKEN>` *(token revoked and rotated as part of Phase 1A)*
- **Impact**: Anyone with read access to this repository or documentation can control the Telegram bot, post arbitrary messages to `@tewsavailable`, or read webhook updates.
- **Required Remediation Plan**:
  1. Revoke the token immediately via Telegram [@BotFather](https://t.me/BotFather) (`/revoke`).
  2. Generate a fresh token and store it securely outside version control.
  3. Replace all instances in documentation and example files with `<YOUR_TELEGRAM_BOT_TOKEN>`.
  4. Rewrite Git history using `git-filter-repo` to permanently erase the secret from all commit objects.
  5. Add an automated pre-commit / CI secret scan (e.g., Gitleaks or Trufflehog).

---

### 1.2 Competing API Surfaces & Inconsistent Security Boundary
- **Location 1**: `main_engine.py` (Lines 541–561)
- **Location 2**: `src/api/app.py` (Lines 216–247)
- **Vulnerability**:
  - `src/api/app.py` enforces SHA-256 API key authentication, daily tiered rate limits, and restricted CORS origins.
  - `main_engine.py` exposes `/api/v1/feed`, `/api/v1/sources`, and `/api/v1/stream` directly on `0.0.0.0:8080` with **zero authentication** and **wildcard CORS** (`Access-Control-Allow-Origin: *`).
- **Impact**: Deployments assuming the FastAPI security layer protects the engine data are completely exposed via the aiohttp engine port.
- **Required Remediation**:
  - Unify API security across all public surfaces or restrict `main_engine.py` to local IPC/localhost.
  - Require API key header verification for data streams or explicit token verification on the SSE endpoint.
  - Replace wildcard CORS with configured allowlists (`API_CORS_ORIGINS`).

---

### 1.3 Insecure TLS Verification Disabled (`ssl=False`)
- **Locations**:
  - `src/bypass/bypass_resolver.py` (Line 119): `connector = aiohttp.TCPConnector(ssl=False)`
  - `src/sources/google_news.py` (Line 164): `session.get(..., ssl=False)`
  - `src/utils/thumbnail.py` (Line 78): `connector = aiohttp.TCPConnector(ssl=False)`
- **Impact**: Disabling SSL certificate verification makes outbound web scraping vulnerable to Man-In-The-Middle (MITM) attacks and DNS spoofing.
- **Required Remediation**: Enable standard TLS certificate verification by default (`ssl=True` or default `SSLContext`). Fallback to unverified SSL only for explicit archive mirrors where certificate chains are historically broken, and log an alert.

---

## 2. P1 High-Severity Security & Reliability Gaps

### 2.1 Denial of Service via Unbounded Synchronous SQLite Queries
- **Locations**: `src/engine/dedup_gate.py` (Line 181), `src/engine/rejected_metadata_store.py` (Line 94).
- **Vulnerability**: Performing synchronous SQLite file locks and commits on the asyncio event loop blocks the entire process from servicing HTTP/SSE clients or processing incoming feeds. Under high feed velocity or on slow SD card storage (Raspberry Pi), the server becomes unresponsive.
- **Remediation**: Migrate all persistence off the main asyncio loop using non-blocking `aiosqlite` or PostgreSQL via `asyncpg`.

---

### 2.2 Unbounded Memory Growth (Denial of Service)
- **Locations**:
  - `src/engine/dedup_gate.py`: All historical MinHash signatures loaded into RAM (`self._minhash_index`) on boot with linear Jaccard comparison across all historical records.
  - `src/events/event_clusterer.py`: `_gc_stale_events()` only evicts events older than 48 hours; if >500 events are created within 48 hours, memory grows without bound.
- **Remediation**: Implement an LRU bounded cache for in-memory signatures and enforce a strict hard limit on active event cluster index size.

---

## 3. P2 & P3 Security Checklist & CI Hardening

| Check | Current Status | Required Action for Phase 9 CI/CD |
|:---|:---:|:---|
| **Secret Scanning in CI** | 🔴 Not Configured | Integrate `gitleaks` in GitHub Actions workflow. |
| **Dependency Vulnerability Scan** | 🔴 Not Configured | Integrate `pip-audit` to scan `requirements.txt`. |
| **Static Security Analysis** | 🔴 Not Configured | Run `bandit -r src/` in test pipeline. |
| **Non-Root Docker Execution** | ✅ Implemented | `Dockerfile` creates and runs as `app:app` system user. |
| **Sensitive Headers Logging** | 🟡 Partial | Audit loggers to ensure `Authorization` and `X-API-Key` headers are never printed to console or logs. |
| **Input Sanitization on Search** | ✅ Implemented | Parameterized SQL queries used in `async_database.py`. |
