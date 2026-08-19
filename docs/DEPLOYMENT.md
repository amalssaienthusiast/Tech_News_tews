# DEPLOYMENT GUIDE

This document describes how to deploy the Tech News Scraper in production,
covering the three deployment modes supported after the P0 production-readiness
hardening.

---

## Quick start: Docker Compose (recommended)

```bash
# 1. Clone and configure
git clone <your-repo-url> tech-news-scraper
cd tech-news-scraper
cp .env.example .env
# Edit .env to set:
#   - GEMINI_API_KEY (for AI features)
#   - NEWSAPI_KEY, BING_API_KEY (for news sources)
#   - API_ALLOW_ANONYMOUS=false (require API keys in production)
#   - API_CORS_ORIGINS=https://your-frontend.example.com
#   - LOG_FORMAT=json (for log aggregators)

# 2. Build and start
docker compose up -d              # app + redis
docker compose --profile full up -d  # + postgres + elasticsearch (optional)

# 3. Verify
curl http://localhost:8000/health
# {"status":"ok","version":"2.0.0","timestamp":"..."}

# 4. Create your first API key (needs pro-tier access — see below)
docker compose exec app python -c "
from src.api.app import api_key_manager
key = api_key_manager.create_key(user_id='admin', tier='pro', name='admin')
print(f'Your API key (save this): {key}')
"

# 5. Use the API
curl -H "X-API-Key: tns_xxx" http://localhost:8000/feed/latest
```

---

## Deployment modes

### Mode 1: Docker Compose (recommended for most teams)

See "Quick start" above. Runs:
- `app` container: aggregator + FastAPI on :8000
- `redis` container: cache + pub/sub
- Optional `postgres`, `elasticsearch`, `celery-worker` (via `--profile full` or `--profile workers`)

**Pros:** One command, reproducible, healthchecks, restart policies, isolated network.
**Cons:** Container overhead (~50MB extra).

### Mode 2: Gunicorn + Uvicorn workers (production-recommended for API)

For high-throughput API deployments, run the aggregator and API as separate
processes:

```bash
# Terminal 1: aggregator (RSS scraping → DB)
python main.py --no-api

# Terminal 2: API (gunicorn + uvicorn workers, 4 processes)
gunicorn src.api.app:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
```

**Pros:** API scales horizontally; aggregator isolation; gunicorn supervises workers (auto-restart on crash).
**Cons:** Two processes to manage — use systemd or supervisord.

#### systemd unit files

`/etc/systemd/system/technews-aggregator.service`:
```ini
[Unit]
Description=Tech News Scraper — Aggregator
After=network.target redis.service

[Service]
Type=simple
User=technews
WorkingDirectory=/opt/technews
EnvironmentFile=/opt/technews/.env
ExecStart=/opt/technews/.venv/bin/python main.py --no-api
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/technews-api.service`:
```ini
[Unit]
Description=Tech News Scraper — API
After=network.target technews-aggregator.service

[Service]
Type=simple
User=technews
WorkingDirectory=/opt/technews
EnvironmentFile=/opt/technews/.env
ExecStart=/opt/technews/.venv/bin/gunicorn src.api.app:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --graceful-timeout 30
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now technews-aggregator technews-api
sudo systemctl status technews-aggregator technews-api
```

### Mode 3: Development (aggregator + supervised API in one process)

```bash
python main.py --with-api
```

Runs the aggregator in the main event loop and the API in a supervised child
process. A watchdog checks `is_alive()` every 5s and restarts the API on crash
(up to 3 attempts). Useful for local development; not recommended for production.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| **API** | | |
| `API_ALLOW_ANONYMOUS` | `false` | Set to `true` to allow unauthenticated requests (free-tier rate limit applies) |
| `API_CORS_ORIGINS` | `http://localhost,http://127.0.0.1` | Comma-separated list of allowed CORS origins |
| **Database** | | |
| `TECHNEWS_DB_PATH` | `data/tech_news.db` | SQLite path for `src.database.Database` |
| `DATABASE_URL` | (none) | SQLAlchemy URL for `DatabaseHandler`. If set, overrides `TECHNEWS_DB_PATH` |
| **Redis** | | |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL (cache + pub/sub) |
| **Logging** | | |
| `LOG_FORMAT` | `text` | `text` (dev) or `json` (production log aggregators) |
| `LOG_FILE` | (none) | Optional file path for logs (in addition to stderr) |
| `LOG_LEVEL` | `INFO` | Logging level |
| **AI** | | |
| `GEMINI_API_KEY` | (none) | Google Gemini API key |
| `OPENAI_API_KEY` | (none) | OpenAI API key (for `LLMSummarizer`) |
| `ANTHROPIC_API_KEY` | (none) | Anthropic API key (for `LLMSummarizer`) |
| `LLM_PROVIDER` | `openai` | Preferred provider: `openai` or `anthropic` |
| **Sources** | | |
| `NEWSAPI_KEY` | (none) | NewsAPI.org API key |
| `BING_API_KEY` | (none) | Bing News API key |
| `GOOGLE_API_KEY` | (none) | Google Custom Search API key |
| `GOOGLE_CSE_ID` | (none) | Google Custom Search Engine ID |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | (none) | Reddit API credentials |
| `TWITTER_BEARER_TOKEN` | (none) | Twitter/X API v2 bearer token |

---

## DB consolidation (migrating from split-brain)

If you have an existing deployment with both `tech_news.db` and `live_feed.db`,
run the one-shot migration:

```bash
# 1. Stop the application
docker compose down  # or: sudo systemctl stop technews-aggregator technews-api

# 2. Dry-run to see what would be migrated
python scripts/migrate_db.py --dry-run

# 3. Run the migration
python scripts/migrate_db.py
# Output: "Migration complete: N migrated, M skipped, 0 failed"
# Source DB renamed to live_feed.db.bak

# 4. Set env vars so both layers use the same file
echo 'TECHNEWS_DB_PATH=/app/data/tech_news.db' >> .env
echo 'DATABASE_URL=sqlite+aiosqlite:////app/data/tech_news.db' >> .env

# 5. Restart
docker compose up -d  # or: sudo systemctl start technews-aggregator technews-api
```

The migration is idempotent — re-running it skips articles that already exist
in the target DB (uses `INSERT OR IGNORE`).

---

## Health checks

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /health` | None | Liveness probe — always 200 if process is up |
| `GET /health/detailed` | None | Includes DB connectivity check |
| `GET /metrics` | None | Prometheus text format |

### Docker healthcheck
The Dockerfile includes:
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
```

### Kubernetes
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
readinessProbe:
  httpGet:
    path: /health/detailed
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
```

---

## API key management

### Create a key
```bash
# Via the API (requires an existing pro-tier key)
curl -X POST -H "X-API-Key: tns_existing_pro_key" \
  "http://localhost:8000/admin/api-keys?user_id=alice&tier=basic&name=alice-key"
# Response: {"api_key":"tns_xxx...","tier":"basic","user_id":"alice"}

# Or directly via Python (bootstrap a first key)
python -c "
from src.api.app import api_key_manager
print(api_key_manager.create_key(user_id='admin', tier='pro', name='bootstrap'))
"
```

### API key tiers
| Tier | Daily limit | Description |
|------|-------------|-------------|
| `free` | 1,000 | Free tier — evaluation only |
| `basic` | 10,000 | Basic tier — small team |
| `pro` | 100,000 | Pro tier — can create new keys |

### Rate limit behavior
- 401 Unauthorized — missing or invalid API key
- 429 Too Many Requests — rate limit exceeded (response body includes remaining count)

---

## Monitoring

### Prometheus
Scrape `GET /metrics` every 15s:
```yaml
scrape_configs:
  - job_name: technews
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: /metrics
    scrape_interval: 15s
```

Available metrics:
- `technews_uptime_seconds` — process uptime
- `technews_feed_requests_total` — counter
- `technews_ws_active_connections` — gauge
- `technews_articles_total` — gauge

### Structured logging
Set `LOG_FORMAT=json` to emit JSON logs:
```json
{"timestamp": "2026-07-24T...", "level": "INFO", "logger": "aggregator", "message": "...", "correlation_id": "..."}
```

Pipe to your log aggregator (ELK, Loki, Datadog, etc.).

---

## Backup

### SQLite
```bash
# Online backup using sqlite3 .backup (safe during writes)
sqlite3 /app/data/tech_news.db ".backup '/backups/tech_news-$(date +%Y%m%d).db'"

# Or via Docker
docker compose exec app sqlite3 /app/data/tech_news.db ".backup '/backups/tech_news-$(date +%Y%m%d).db'"
```

### PostgreSQL (if using `--profile full`)
```bash
docker compose exec postgres pg_dump -U technews technews > backups/technews-$(date +%Y%m%d).sql
```

---

## Troubleshooting

### API returns 401
- Verify `API_ALLOW_ANONYMOUS=false` in `.env`
- Verify the `X-API-Key` header is present and correct
- Check that the key exists in the `api_keys` table: `sqlite3 /app/data/tech_news.db "SELECT key_id, tier, enabled FROM api_keys"`

### API returns 429
- Rate limit exceeded for the day. Wait until midnight UTC (reset time), or upgrade tier.

### `ModuleNotFoundError: No module named 'sqlalchemy'`
- Run `pip install -r requirements.txt` — the P0-B changes added SQLAlchemy, asyncpg, curl-cffi, defusedxml, and gunicorn to requirements.

### Database is empty after migration
- Check that `TECHNEWS_DB_PATH` and `DATABASE_URL` point at the same file.
- Run `python scripts/migrate_db.py --dry-run` to verify the source DB has rows.

### API process keeps crashing
- Check logs: `docker compose logs app` or `journalctl -u technews-api -f`
- The supervised mode (`--with-api`) will restart up to 3 times; after that it gives up and the aggregator continues without the API.
- For production, use gunicorn (Mode 2) which restarts workers indefinitely.
