# Operational Runbook: Backup & Disaster Recovery

## 1. Overview

This document describes procedures for taking online live database backups and restoring from catastrophic data corruption or host failure.

---

## 2. Automated Scheduled Online Backup

SQLite online backup API performs point-in-time snapshots without locking writers or readers.

### Executing Live Backup via CLI
```bash
# Automated cron execution (run every 6 hours)
BACKUP_DIR="/data/backups"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
mkdir -p "${BACKUP_DIR}"

sqlite3 /data/canonical_technews.db ".backup '${BACKUP_DIR}/technews_backup_${TIMESTAMP}.db'"

# Verify backup integrity
sqlite3 "${BACKUP_DIR}/technews_backup_${TIMESTAMP}.db" "PRAGMA integrity_check;"
```

---

## 3. Disaster Restoration Procedure

### Step 1: Stop Ingestion & API Services
```bash
docker stop technews_api
```

### Step 2: Archive Corrupted Database
```bash
mv /data/canonical_technews.db /data/corrupted_technews_$(date +%s).db
mv /data/canonical_technews.db-wal /data/corrupted_technews_$(date +%s).db-wal 2>/dev/null || true
```

### Step 3: Restore From Latest Verified Snapshot
```bash
LATEST_BACKUP=$(ls -t /data/backups/technews_backup_*.db | head -n 1)
cp "${LATEST_BACKUP}" /data/canonical_technews.db
```

### Step 4: Verify Restored Database Integrity
```bash
sqlite3 /data/canonical_technews.db "PRAGMA integrity_check;"
sqlite3 /data/canonical_technews.db "PRAGMA foreign_key_check;"
sqlite3 /data/canonical_technews.db "SELECT count(*) FROM canonical_articles;"
```

### Step 5: Restart Services
```bash
docker start technews_api
curl -f http://localhost:8000/health
```
