# Production Environment Contract

**Authoritative Environment Variable Specification**  
**Phase**: Phase 8 Engineering Hardening — Gate 8E-H3  
**Status**: 🟢 ACTIVE & ENFORCED  
**Date**: `2026-08-17`  

---

## 1. Core Principles

1. **Explicit Precedence**: Environment configuration overrides internal file defaults.
2. **Fail-Closed Security**: In production (`TECHNEWS_ENV=production`), missing administrative or read-write credentials cause immediate authentication rejection (401 Unauthorized).
3. **Immutability of Storage Contract**: `TECHNEWS_DB_PATH` is shared across API and Worker containers via persistent volume mounts.

---

## 2. Environment Variables Matrix

| Variable | Type | Required / Optional | Default Value | Production Behavior | Security Sensitivity | Owning Component |
|---|---|---|---|---|---|---|
| `TECHNEWS_ENV` | String | **Required** | `development` | Set to `production` in staging/production. Enforces strict RBAC and disables insecure defaults. | **MEDIUM** | Global / Auth |
| `TECHNEWS_DB_PATH` | Path | Optional | `data/technews_canonical.db` (Local) / `/data/canonical_technews.db` (Docker) | Points both API and Worker processes to the shared SQLite WAL database. | **HIGH** | `SqliteEngine` |
| `TECHNEWS_CANONICAL_DB_PATH` | Path | Optional | Same as `TECHNEWS_DB_PATH` | Alias for `TECHNEWS_DB_PATH`. | **HIGH** | `SqliteEngine` |
| `TECHNEWS_ADMIN_API_KEY` | String | **Required in Prod** | None | Grants `admin` role across API endpoints. Required in production. | **CRITICAL** (Secret) | `EnvAuthManager` |
| `TECHNEWS_RW_API_KEY` | String | **Required in Prod** | None | Grants `read_write` role across API endpoints. Required in production. | **CRITICAL** (Secret) | `EnvAuthManager` |
| `TECHNEWS_RO_API_KEY` | String | **Required in Prod** | None | Grants `read_only` role across API endpoints. Required in production. | **CRITICAL** (Secret) | `EnvAuthManager` |
| `ENGINE_API_KEY` | String | Optional | None | Legacy engine access key. Fails closed in production if unset. | **CRITICAL** (Secret) | `src/security/policy.py` |
| `TECHNEWS_LOG_LEVEL` | String | Optional | `INFO` | Configures Python logging severity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | **LOW** | Logging / CLI |
| `TECHNEWS_WORKER_CONCURRENCY` | Integer | Optional | `2` | Number of concurrent async task batches executed per worker species. | **LOW** | `src.worker` |
| `TECHNEWS_ENABLE_PROMETHEUS` | Boolean | Optional | `true` | Enables metrics collection on `/metrics` endpoint. | **LOW** | `PrometheusMetricsMiddleware` |
| `CANONICAL_PIPELINE_MODE` | String | Optional | `active` | Pipeline execution mode (`active`, `shadow`, `legacy`). | **MEDIUM** | `UnifiedFeedChainEngine` |
| `ALLOW_ANONYMOUS_READS` | Boolean | Optional | `false` in Prod | When `false`, all GET endpoints require a valid API key. | **HIGH** | `src/api/app.py` |

---

## 3. Storage Ownership & Concurrency Model

```text
                           CONTAINER VOLUME: /data
                                      │
               ┌──────────────────────┴──────────────────────┐
               ▼                                             ▼
  INGESTION WORKER PROCESS                      API SERVER PROCESS (Uvicorn)
  (python -m src.worker)                        (uvicorn src.api.app:app)
  • Read-Write Master                           • Read-Only / Query Client
  • Single Writer via WAL                       • Multi-Reader Non-Blocking WAL
  • Explicit Atomic Transactions                • Read Committed Snapshot
  • Schema Migration Owner                      • Schema Consumer / Read-Only Check
```

### Storage Parameters:
- **Journal Mode**: `PRAGMA journal_mode = WAL;`
- **Synchronous Flag**: `PRAGMA synchronous = NORMAL;`
- **Busy Timeout**: `PRAGMA busy_timeout = 5000;` (5 seconds)
- **Foreign Keys**: `PRAGMA foreign_keys = ON;`
- **Page Cache**: `PRAGMA cache_size = -64000;` (64 MB in-memory cache)
- **FTS5 Virtual Index**: Search index automatically synced on article insert/update.
