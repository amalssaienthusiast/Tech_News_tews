# Configuration & Environment Variables Inventory

**Document Status**: Phase 0 Baseline  
**Scope**: Configuration files (`.env`, `.env.example`, `config.yaml`, `config/settings.py`), all 60 environment variables, defaults, and port/host inconsistencies.

---

## 1. Configuration Sources & Hierarchy

Current configuration is split across 5 competing locations:
1. `.env` / `.env.example` (Root environment file)
2. `config/config.yaml` (YAML-based scraper source list and refresh intervals)
3. `config/settings.py` (Pydantic / Dataclass settings schema)
4. CLI Flag Defaults (`main_engine.py`, `main.py`, `telegram_feeder_bot.py`, `cli.py`)
5. Hardcoded Defaults inside individual modules

### Target Hierarchy (Single Source of Truth)
`Default Schema (Pydantic Settings)` ➔ `config.yaml (Overrides)` ➔ `.env (Local Secrets)` ➔ `OS Environment (Production)` ➔ `Validated Typed Settings Object`

---

## 2. Complete Environment Variables Master Index

| Variable Name | Type | Default Value | Used In | Purpose / Domain | Secret? |
|:---|:---:|:---:|:---|:---|:---:|
| `ENGINE_PORT` | `int` | `8080` | `main_engine.py`, `docker-compose.yml` | HTTP/SSE server port | No |
| `ENGINE_HOST` | `str` | `0.0.0.0` | `main_engine.py` | Bind host address | No |
| `ENGINE_API_URL` | `str` | `http://localhost:8080` | `telegram_feeder_bot.py`, `main_engine.py` | Central engine URL | No |
| `API_ALLOW_ANONYMOUS`| `bool`| `false` | `src/api/app.py` | Allow unauthenticated API calls | No |
| `API_CORS_ORIGINS` | `str` | `http://localhost,http://127.0.0.1` | `src/api/app.py` | Allowed CORS origins (comma-separated) | No |
| `TELEGRAM_BOT_TOKEN` | `str` | `None` | `telegram_feeder_bot.py`, `DEPLOYMENT_PI.md` | Telegram Bot API token | 🔴 YES |
| `TELEGRAM_CHAT_ID` | `str` | `None` | `telegram_feeder_bot.py`, `DEPLOYMENT_PI.md` | Target Telegram channel/chat | No |
| `DATABASE_URL` | `str` | `sqlite:///data/technews.db` | `src/db_storage/async_database.py` | PostgreSQL or SQLite database URL | 🟡 (if PG) |
| `TECHNEWS_DB_PATH` | `str` | `data/technews.db` | `src/database.py` | SQLite fallback database file path | No |
| `STORAGE_MODE` | `str` | `sqlite` | `src/db_storage/unified_storage.py` | Database backend selector (`sqlite`/`postgres`)| No |
| `REDIS_URL` | `str` | `redis://localhost:6379/0` | `src/db_storage/ephemeral_store.py` | Redis connection URL | 🟡 (if auth) |
| `CELERY_BROKER_URL` | `str` | `redis://localhost:6379/1` | `src/queue/celery_app.py` | Celery broker connection string | 🟡 (if auth) |
| `CELERY_RESULT_BACKEND`| `str`| `redis://localhost:6379/2` | `src/queue/celery_app.py` | Celery task result backend | 🟡 (if auth) |
| `ELASTICSEARCH_URL` | `str` | `http://localhost:9200` | `src/search/elastic_client.py` | Elasticsearch host URL | No |
| `ELASTICSEARCH_API_KEY`| `str`| `None` | `src/search/elastic_client.py` | Elasticsearch API key | 🔴 YES |
| `ELASTICSEARCH_CLOUD_ID`| `str`| `None` | `src/search/elastic_client.py` | Elastic Cloud deployment ID | No |
| `ELASTICSEARCH_INDEX` | `str` | `technews_articles` | `src/search/elastic_client.py` | Target search index name | No |
| `GEMINI_API_KEY` | `str` | `None` | `src/intelligence/llm_client.py` | Google Gemini API key | 🔴 YES |
| `OPENAI_API_KEY` | `str` | `None` | `src/intelligence/llm_client.py` | OpenAI API key | 🔴 YES |
| `ANTHROPIC_API_KEY` | `str` | `None` | `src/intelligence/llm_client.py` | Anthropic Claude API key | 🔴 YES |
| `LLM_PROVIDER` | `str` | `hybrid` | `src/intelligence/llm_client.py` | Active LLM provider (`gemini`/`openai`/`anthropic`/`local`)| No |
| `LLM_MODEL` | `str` | `gemini-1.5-flash` | `src/intelligence/llm_client.py` | Default model identifier | No |
| `LLM_TEMPERATURE` | `float`| `0.2` | `src/intelligence/llm_client.py` | Inference temperature | No |
| `LLM_FALLBACK_LOCAL`| `bool`| `true` | `src/intelligence/llm_client.py` | Fallback to rule-based parser on LLM error | No |
| `GITHUB_TOKEN` | `str` | `None` | `src/zombies/z_github.py` | GitHub Personal Access Token (for quota) | 🔴 YES |
| `GOOGLE_API_KEY` | `str` | `None` | `src/sources/google_custom_search.py` | Google Cloud API key | 🔴 YES |
| `GOOGLE_CSE_ID` | `str` | `None` | `src/sources/google_custom_search.py` | Google Custom Search Engine ID | No |
| `NEWSAPI_KEY` | `str` | `None` | `src/sources/newsapi_source.py` | NewsAPI.org developer key | 🔴 YES |
| `BING_API_KEY` | `str` | `None` | `src/sources/bing_news.py` | Microsoft Bing News API key | 🔴 YES |
| `REDDIT_CLIENT_ID` | `str` | `None` | `src/sources/reddit_source.py` | Reddit OAuth App Client ID | No |
| `REDDIT_CLIENT_SECRET`| `str`| `None` | `src/sources/reddit_source.py` | Reddit OAuth App Secret | 🔴 YES |
| `TWITTER_BEARER_TOKEN`| `str`| `None` | `src/sources/twitter_source.py` | X / Twitter API v2 Bearer Token | 🔴 YES |
| `SERPAPI_KEY` | `str` | `None` | `src/sources/serpapi_source.py` | SerpAPI search key | 🔴 YES |
| `BEEHIIV_API_KEY` | `str` | `None` | `src/newsletter/publishers/beehiiv.py` | Beehiiv newsletter API token | 🔴 YES |
| `BEEHIIV_PUBLICATION_ID`| `str`| `None` | `src/newsletter/publishers/beehiiv.py` | Beehiiv publication identifier | No |
| `SLACK_WEBHOOK_URL` | `str` | `None` | `src/notifications/slack_notifier.py` | Slack incoming webhook | 🔴 YES |
| `DISCORD_WEBHOOK_URL`| `str` | `None` | `src/notifications/discord_notifier.py` | Discord webhook URL | 🔴 YES |
| `SMTP_SERVER` / `SMTP_HOST` | `str` | `smtp.gmail.com` | `src/notifications/email_notifier.py` | Outbound mail server hostname | No |
| `SMTP_PORT` | `int` | `587` | `src/notifications/email_notifier.py` | Mail server port | No |
| `SMTP_USER` / `SMTP_EMAIL` | `str` | `None` | `src/notifications/email_notifier.py` | Outbound SMTP username / email | No |
| `SMTP_PASSWORD` | `str` | `None` | `src/notifications/email_notifier.py` | SMTP authentication password | 🔴 YES |
| `WEBSOCKET_HOST` | `str` | `0.0.0.0` | `src/realtime/websocket_server.py` | Dedicated WebSocket host | No |
| `WEBSOCKET_PORT` | `int` | `8765` | `src/realtime/websocket_server.py` | Dedicated WebSocket port | No |
| `LOG_LEVEL` | `str` | `INFO` | `config/settings.py` | Logging level (`DEBUG`/`INFO`/`WARNING`/`ERROR`)| No |
| `LOG_FORMAT` | `str` | `text` | `config/settings.py` | Log formatting mode (`text` or `json`) | No |

---

## 3. Configuration Inconsistencies to Resolve in Phase 1

1. **Port Inconsistency**:
   - `Dockerfile`: `EXPOSE 8000` & `HEALTHCHECK ... :8000/health`
   - `docker-compose.yml`: `ports: 8080:8080` & `HEALTHCHECK ... :8080/api/v1/health`
   - `main_engine.py`: Default port `8080`
   - `main.py`: Default port `8000`
   - **Resolution Target**: Standardize container and engine port to `8080` everywhere.
2. **Duplicate Environment Keys**:
   - SMTP host referenced as both `SMTP_SERVER` and `SMTP_HOST`
   - SMTP user referenced as both `SMTP_USER` and `SMTP_EMAIL`
   - **Resolution Target**: Standardize on `SMTP_HOST` and `SMTP_USER`.
