-- =============================================================================
-- SQLite Canonical Persistence Schema (Phase 5)
-- Location: src/storage/schema_sqlite.sql
-- =============================================================================

-- Performance & Reliability Pragmas
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 10000;

-- -----------------------------------------------------------------------------
-- 1. TechEvent Aggregate Root Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_events (
    id TEXT PRIMARY KEY,
    headline TEXT NOT NULL,
    first_seen TEXT NOT NULL,                         -- ISO-8601 UTC string
    last_updated TEXT NOT NULL,                       -- ISO-8601 UTC string
    entities TEXT NOT NULL DEFAULT '[]',              -- JSON Array of string entity names
    topics TEXT NOT NULL DEFAULT '[]',                -- JSON Array of string topic tags
    primary_source TEXT,
    confidence REAL NOT NULL DEFAULT 0.0,
    importance REAL NOT NULL DEFAULT 0.5,
    novelty REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'suspected',         -- Enum: suspected, corroborated, confirmed, developing, resolved, stale
    freshness TEXT NOT NULL DEFAULT 'fresh',          -- Enum: breaking, fresh, recent, aged, stale
    freshness_score REAL NOT NULL DEFAULT 0.0,
    cluster_id TEXT NOT NULL DEFAULT '',
    category TEXT,
    source_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_canonical_events_status ON canonical_events(status);
CREATE INDEX IF NOT EXISTS idx_canonical_events_freshness ON canonical_events(freshness);
CREATE INDEX IF NOT EXISTS idx_canonical_events_last_updated ON canonical_events(last_updated DESC);

-- -----------------------------------------------------------------------------
-- 2. EventSourceEvidence Child Entity Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_event_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_tier INTEGER NOT NULL DEFAULT 2,          -- Enum integer: 1=Premium, 2=Specialist, 3=Community, 4=Discovery
    discovered_at TEXT NOT NULL,                     -- ISO-8601 UTC string
    published_at TEXT,                                -- ISO-8601 UTC string
    summary TEXT NOT NULL DEFAULT '',
    image_url TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0,            -- Boolean: 0 or 1
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (event_id) REFERENCES canonical_events(id) ON DELETE CASCADE,
    UNIQUE(event_id, url)
);

CREATE INDEX IF NOT EXISTS idx_canonical_event_sources_event_id ON canonical_event_sources(event_id);
CREATE INDEX IF NOT EXISTS idx_canonical_event_sources_article_id ON canonical_event_sources(article_id);

-- -----------------------------------------------------------------------------
-- 3. TimelineEntry Child Entity Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_event_timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,                          -- ISO-8601 UTC string
    headline TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    confidence_at_time REAL NOT NULL DEFAULT 0.0,
    entry_type TEXT NOT NULL DEFAULT 'update',        -- initial, update, confirmation, resolution
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (event_id) REFERENCES canonical_events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_canonical_event_timeline_event_id ON canonical_event_timeline(event_id);

-- -----------------------------------------------------------------------------
-- 4. NormalizedArticle Storage Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_articles (
    id TEXT PRIMARY KEY,                              -- sha256(canonical_url)[:16]
    canonical_url TEXT UNIQUE NOT NULL,
    original_url TEXT NOT NULL,
    title TEXT NOT NULL,
    clean_text TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_tier TEXT NOT NULL,
    zombie_species TEXT NOT NULL,
    discovered_at TEXT NOT NULL,                     -- ISO-8601 UTC string
    published_at TEXT,                                -- ISO-8601 UTC string
    language TEXT NOT NULL DEFAULT 'en',
    image_url TEXT,
    authors TEXT NOT NULL DEFAULT '[]',               -- JSON Array of author strings
    tags TEXT NOT NULL DEFAULT '[]',                  -- JSON Array of tag strings
    metadata TEXT NOT NULL DEFAULT '{}',              -- JSON Object of additional metadata
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_canonical_articles_canonical_url ON canonical_articles(canonical_url);
CREATE INDEX IF NOT EXISTS idx_canonical_articles_discovered_at ON canonical_articles(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_canonical_articles_source_id ON canonical_articles(source_id);
CREATE INDEX IF NOT EXISTS idx_canonical_articles_published_at ON canonical_articles(published_at DESC);

-- -----------------------------------------------------------------------------
-- 4.1 Canonical Articles FTS5 Full-Text Index & Sync Triggers
-- -----------------------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS canonical_articles_fts USING fts5(
    id UNINDEXED,
    title,
    clean_text,
    summary,
    tags,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- FTS Synchronization Triggers
CREATE TRIGGER IF NOT EXISTS trg_canonical_articles_fts_insert
AFTER INSERT ON canonical_articles
BEGIN
    INSERT INTO canonical_articles_fts(id, title, clean_text, summary, tags)
    VALUES (new.id, new.title, new.clean_text, new.summary, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS trg_canonical_articles_fts_delete
AFTER DELETE ON canonical_articles
BEGIN
    DELETE FROM canonical_articles_fts WHERE id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_canonical_articles_fts_update
AFTER UPDATE ON canonical_articles
BEGIN
    DELETE FROM canonical_articles_fts WHERE id = old.id;
    INSERT INTO canonical_articles_fts(id, title, clean_text, summary, tags)
    VALUES (new.id, new.title, new.clean_text, new.summary, new.tags);
END;

-- -----------------------------------------------------------------------------
-- 5. SourceHealth Resilience State Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_source_health (
    source_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'healthy',           -- Enum: healthy, degraded, cooldown, rate_limited, quarantined, probation, dead
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    last_attempt TEXT,                                -- ISO-8601 UTC string
    last_success TEXT,                                -- ISO-8601 UTC string
    last_status_code INTEGER,
    cooldown_until TEXT,                              -- ISO-8601 UTC string
    rate_limit_reset_at TEXT,                         -- ISO-8601 UTC string
    working_bypass_tier INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_canonical_source_health_status ON canonical_source_health(status);

-- -----------------------------------------------------------------------------
-- 6. User Personalization & Preferences Tables
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT 'User',
    theme TEXT NOT NULL DEFAULT 'tokyo_night',
    articles_per_page INTEGER NOT NULL DEFAULT 20,
    reading_history_enabled INTEGER NOT NULL DEFAULT 1,
    delivery_settings TEXT NOT NULL DEFAULT '{}',     -- JSON serialized DeliverySettings
    alert_thresholds TEXT NOT NULL DEFAULT '{}',      -- JSON serialized AlertThresholds
    created_at TEXT NOT NULL,                         -- ISO-8601 UTC string
    updated_at TEXT NOT NULL                          -- ISO-8601 UTC string
);

CREATE TABLE IF NOT EXISTS user_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    keywords TEXT NOT NULL DEFAULT '[]',              -- JSON Array
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES user_preferences(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, topic)
);

CREATE INDEX IF NOT EXISTS idx_user_topics_user ON user_topics(user_id);

CREATE TABLE IF NOT EXISTS user_watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    ticker TEXT,
    aliases TEXT NOT NULL DEFAULT '[]',               -- JSON Array
    priority INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES user_preferences(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, company_name)
);

CREATE INDEX IF NOT EXISTS idx_user_watchlist_user ON user_watchlist(user_id);

CREATE TABLE IF NOT EXISTS user_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    preferred INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0,
    trust_score REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES user_preferences(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, source_domain)
);

CREATE INDEX IF NOT EXISTS idx_user_sources_user ON user_sources(user_id);

CREATE TABLE IF NOT EXISTS user_bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES user_preferences(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_user_bookmarks_user ON user_bookmarks(user_id);

CREATE TABLE IF NOT EXISTS user_reading_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    read_at TEXT NOT NULL,                            -- ISO-8601 UTC string
    time_spent_seconds INTEGER NOT NULL DEFAULT 0,
    clicked_links INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES user_preferences(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_reading_history_user ON user_reading_history(user_id);
