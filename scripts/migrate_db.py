#!/usr/bin/env python3
"""
One-shot migration script: consolidate the two split-brain SQLite databases
into a single tech_news.db.

Background (audit §9.3):
  - src/database.py:Database writes to data/tech_news.db (sync sqlite3).
  - src/db_storage/db_handler.py:DatabaseHandler writes to live_feed.db
    (async SQLAlchemy). The two schemas are different and the two layers
    never shared data — articles scraped via main.py never got intelligence
    analysis; articles scraped via the orchestrator never reached the API.

After P0-E, both layers honor the TECHNEWS_DB_PATH env var (or DATABASE_URL)
and can point at the same file. This script:

  1. Reads all rows from live_feed.db (table: live_articles).
  2. Inserts them into tech_news.db (table: articles) using INSERT OR IGNORE
     (so re-running the script is safe — existing articles are kept).
  3. Logs a summary of rows migrated, skipped, and failed.
  4. Optionally renames live_feed.db to live_feed.db.bak (default: yes;
     use --no-backup to skip).

Usage:
  python scripts/migrate_db.py                    # uses default paths
  python scripts/migrate_db.py --source path/to/live_feed.db
  python scripts/migrate_db.py --target path/to/tech_news.db
  python scripts/migrate_db.py --dry-run          # report only, no writes
  python scripts/migrate_db.py --no-backup        # don't rename the source

Exit codes:
  0 — success (or dry-run completed)
  1 — source DB not found
  2 — target DB initialization failed
  3 — migration failed partway
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("migrate_db")

# Schema mapping: live_articles (source) → articles (target)
# Source columns (from src/db_storage/db_handler.py:ArticleModel):
#   id, title, url, source, published_at, scraped_at, description,
#   content, media_url, categories, metadata_json
#
# Target columns (from src/database.py:_create_schema):
#   id, title, url, source, published, scraped_at, ai_summary, full_content
#
# Mapping logic:
#   id          -> id
#   title       -> title
#   url         -> url
#   source      -> source
#   published_at -> published  (column rename; format may differ — see below)
#   scraped_at  -> scraped_at
#   (none)      -> ai_summary  (set to NULL; LLM not run on legacy data)
#   content     -> full_content
#
# Note: description, media_url, categories, metadata_json from the source
# are NOT migrated because the target schema does not have columns for them.
# They are preserved in the metadata_json column of the source DB, which is
# renamed to .bak at the end of the migration.


def find_source_db() -> Path:
    """Find the live_feed.db file."""
    # Try CWD first (legacy default)
    cwd_path = Path("live_feed.db")
    if cwd_path.exists():
        return cwd_path
    # Then try DATA_DIR
    try:
        from config.settings import DATA_DIR
        data_path = DATA_DIR / "live_feed.db"
        if data_path.exists():
            return data_path
    except ImportError:
        pass
    return cwd_path  # return the default; caller will error if not found


def find_target_db() -> Path:
    """Find the tech_news.db file (or env-var-overridden path)."""
    from config.settings import DB_FILE
    return DB_FILE


def migrate(source_path: Path, target_path: Path, dry_run: bool = False) -> dict:
    """Migrate articles from source DB to target DB.

    Returns a dict: {migrated, skipped, failed, total}.
    """
    if not source_path.exists():
        log.error("Source DB not found: %s", source_path)
        sys.exit(1)

    log.info("Source DB: %s (%d bytes)", source_path, source_path.stat().st_size)
    log.info("Target DB: %s", target_path)

    # Connect to source
    src = sqlite3.connect(source_path)
    src.row_factory = sqlite3.Row

    # Verify the source table exists
    src_cursor = src.cursor()
    src_cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='live_articles'"
    )
    if not src_cursor.fetchone():
        log.error("Source DB has no 'live_articles' table. Nothing to migrate.")
        src.close()
        return {"migrated": 0, "skipped": 0, "failed": 0, "total": 0}

    # Count source rows
    src_cursor.execute("SELECT COUNT(*) FROM live_articles")
    total = src_cursor.fetchone()[0]
    log.info("Found %d articles in source DB", total)

    if dry_run:
        log.info("[dry-run] Would migrate %d articles. No changes made.", total)
        src.close()
        return {"migrated": 0, "skipped": 0, "failed": 0, "total": total}

    # Ensure target parent dir exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Connect to target
    tgt = sqlite3.connect(target_path)
    tgt.row_factory = sqlite3.Row

    migrated = 0
    skipped = 0
    failed = 0

    src_cursor.execute("""
        SELECT id, title, url, source, published_at, scraped_at, description, content
        FROM live_articles
    """)

    for row in src_cursor:
        try:
            # Convert published_at (datetime obj or ISO string) to ISO string
            pub = row["published_at"]
            if pub is None:
                published = None
            elif isinstance(pub, str):
                published = pub
            else:
                # datetime object
                published = pub.isoformat() if hasattr(pub, "isoformat") else str(pub)

            # Convert scraped_at similarly
            scr = row["scraped_at"]
            if scr is None:
                scraped_at = datetime.utcnow().isoformat()
            elif isinstance(scr, str):
                scraped_at = scr
            else:
                scraped_at = scr.isoformat() if hasattr(scr, "isoformat") else str(scr)

            tgt_cursor = tgt.cursor()
            tgt_cursor.execute(
                """INSERT OR IGNORE INTO articles
                   (id, title, url, source, published, scraped_at, ai_summary, full_content)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    row["id"],
                    row["title"],
                    row["url"],
                    row["source"],
                    published,
                    scraped_at,
                    row["content"] or "",
                ),
            )
            if tgt_cursor.rowcount > 0:
                migrated += 1
            else:
                skipped += 1
        except Exception as e:
            log.warning("Failed to migrate article id=%s: %s", row["id"], e)
            failed += 1

    tgt.commit()
    tgt.close()
    src.close()

    log.info(
        "Migration complete: %d migrated, %d skipped (already existed), %d failed, %d total",
        migrated, skipped, failed, total,
    )
    return {"migrated": migrated, "skipped": skipped, "failed": failed, "total": total}


def backup_source(source_path: Path) -> Path | None:
    """Rename the source DB to <name>.bak. Returns the backup path or None."""
    if not source_path.exists():
        return None
    backup_path = source_path.with_suffix(source_path.suffix + ".bak")
    if backup_path.exists():
        # Append timestamp to avoid overwriting an existing backup
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = source_path.with_suffix(f"{source_path.suffix}.bak.{ts}")
    shutil.move(source_path, backup_path)
    log.info("Renamed source DB to: %s", backup_path)
    return backup_path


def main() -> None:
    p = argparse.ArgumentParser(description="Consolidate live_feed.db into tech_news.db")
    p.add_argument("--source", type=Path, help="Path to source live_feed.db (default: auto-detect)")
    p.add_argument("--target", type=Path, help="Path to target tech_news.db (default: auto-detect)")
    p.add_argument("--dry-run", action="store_true", help="Report only; no changes made")
    p.add_argument("--no-backup", action="store_true", help="Don't rename the source DB after migration")
    args = p.parse_args()

    source_path = args.source or find_source_db()
    target_path = args.target or find_target_db()

    stats = migrate(source_path, target_path, dry_run=args.dry_run)

    if args.dry_run or stats["failed"] > 0:
        # Don't backup if dry-run or if migration had failures
        sys.exit(0 if args.dry_run else 3)

    if not args.no_backup:
        backup_source(source_path)

    log.info("Done. Set TECHNEWS_DB_PATH=%s in your .env so both DB layers use it.", target_path)


if __name__ == "__main__":
    main()
