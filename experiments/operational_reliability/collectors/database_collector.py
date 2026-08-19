"""
Database Telemetry and Health Collector.
Location: experiments/operational_reliability/collectors/database_collector.py

Periodically audits SQLite database sizing, WAL file growth, page metrics,
table row counts, and runs full PRAGMA integrity checks.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Dict


class DatabaseCollector:
    """Collects SQLite database statistics and integrity checks."""

    def __init__(self, db_path: Path, output_dir: Path):
        self.db_path = db_path
        self.wal_path = Path(str(db_path) + "-wal")
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def collect_stats(self) -> Dict[str, Any]:
        """Query SQLite page metrics, file sizes, and table counts."""
        db_size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        wal_size_bytes = self.wal_path.stat().st_size if self.wal_path.exists() else 0

        page_count = 0
        page_size = 4096
        article_count = 0
        event_count = 0
        fts_count = 0

        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=5.0)
                cursor = conn.cursor()
                cursor.execute("PRAGMA page_count;")
                page_count = cursor.fetchone()[0]
                cursor.execute("PRAGMA page_size;")
                page_size = cursor.fetchone()[0]

                # Row counts
                try:
                    cursor.execute("SELECT COUNT(*) FROM articles;")
                    article_count = cursor.fetchone()[0]
                except Exception:
                    pass

                try:
                    cursor.execute("SELECT COUNT(*) FROM tech_events;")
                    event_count = cursor.fetchone()[0]
                except Exception:
                    pass

                try:
                    cursor.execute("SELECT COUNT(*) FROM articles_fts;")
                    fts_count = cursor.fetchone()[0]
                except Exception:
                    pass

                conn.close()
            except Exception:
                pass

        stats = {
            "db_size_bytes": db_size_bytes,
            "db_size_mb": round(db_size_bytes / (1024 * 1024), 2),
            "wal_size_bytes": wal_size_bytes,
            "wal_size_mb": round(wal_size_bytes / (1024 * 1024), 2),
            "page_count": page_count,
            "page_size": page_size,
            "article_count": article_count,
            "event_count": event_count,
            "fts_entry_count": fts_count,
        }

        # Save stats json
        stats_file = self.output_dir / "sqlite_stats.json"
        stats_file.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        return stats

    def run_integrity_check(self) -> Dict[str, Any]:
        """Execute PRAGMA integrity_check and PRAGMA foreign_key_check."""
        integrity_ok = False
        foreign_keys_ok = False
        integrity_output = []
        fk_output = []

        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=10.0)
                cursor = conn.cursor()

                cursor.execute("PRAGMA integrity_check;")
                integrity_rows = cursor.fetchall()
                integrity_output = [r[0] for r in integrity_rows]
                integrity_ok = (len(integrity_rows) == 1 and integrity_rows[0][0] == "ok")

                cursor.execute("PRAGMA foreign_key_check;")
                fk_rows = cursor.fetchall()
                fk_output = [str(r) for r in fk_rows]
                foreign_keys_ok = (len(fk_rows) == 0)

                conn.close()
            except Exception as e:
                integrity_output = [f"Integrity check error: {e}"]

        report_text = f"=== PRAGMA integrity_check ===\nStatus: {'OK' if integrity_ok else 'FAILED'}\n"
        report_text += "\n".join(integrity_output) + "\n\n"
        report_text += f"=== PRAGMA foreign_key_check ===\nStatus: {'OK' if foreign_keys_ok else 'FAILED'}\n"
        report_text += "\n".join(fk_output) if fk_output else "No violations.\n"

        (self.output_dir / "integrity_check.txt").write_text(report_text, encoding="utf-8")

        return {
            "integrity_check_passed": integrity_ok,
            "foreign_key_check_passed": foreign_keys_ok,
            "integrity_output": integrity_output,
            "fk_output": fk_output,
        }
