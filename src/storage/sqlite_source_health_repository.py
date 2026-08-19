"""
SQLite-backed Canonical Source Health Repository.
Location: src/storage/sqlite_source_health_repository.py

Implements SourceHealthRepositoryProtocol for SourceHealth resilience entities:
- Asynchronous persistence using SqliteEngine
- Strict domain round-trip mapping for mutable operational states
- Deterministic upsert on immutable source_id
- Exact SourceHealthStatus enum validation and serialization
- Timezone-aware UTC datetimes for all tracking and cooldown fields
- Atomic batch operations with transactional rollback
- Clean-context restart durability and WAL concurrency support
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import aiosqlite

from ..domain.enums import SourceHealthStatus
from ..domain.models import SourceHealth
from ..domain.validators import DomainValidationError, validate_utc_datetime
from .protocols import SourceHealthRepositoryProtocol
from .sqlite_engine import SqliteEngine

logger = logging.getLogger(__name__)


def _normalize_datetime(dt: Optional[datetime], field_name: str) -> Optional[datetime]:
    """Validate timezone awareness and normalize to UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise DomainValidationError(f"Datetime field '{field_name}' must be timezone-aware (naive given: {dt})")
    return dt.astimezone(UTC)


def _parse_status(val: Any) -> SourceHealthStatus:
    """Parse SourceHealthStatus safely or raise DomainValidationError on invalid values."""
    if isinstance(val, SourceHealthStatus):
        return val
    if isinstance(val, str):
        try:
            return SourceHealthStatus(val.strip().lower())
        except ValueError:
            raise DomainValidationError(f"Invalid SourceHealthStatus value: '{val}'")
    raise DomainValidationError(f"Expected SourceHealthStatus or str, got {type(val)}")


class SqliteSourceHealthRepository(SourceHealthRepositoryProtocol):
    """
    SQLite-backed asynchronous repository for SourceHealth operational state.
    """

    def __init__(self, engine: Optional[SqliteEngine] = None, auto_init: bool = True) -> None:
        self.engine = engine or SqliteEngine()
        self._auto_init = auto_init
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self) -> None:
        """Initialize schema idempotently on first call if auto_init is enabled."""
        if not self._auto_init or self._initialized:
            return
        async with self._init_lock:
            if not self._initialized:
                await self.engine.initialize_schema()
                self._initialized = True

    def _health_to_params(self, health: SourceHealth) -> Dict[str, Any]:
        """Convert a SourceHealth domain model into parameterized SQL values."""
        status_enum = _parse_status(health.status)

        last_attempt = _normalize_datetime(health.last_attempt, "last_attempt")
        last_success = _normalize_datetime(health.last_success, "last_success")
        cooldown_until = _normalize_datetime(health.cooldown_until, "cooldown_until")
        rate_limit_reset = _normalize_datetime(health.rate_limit_reset_at, "rate_limit_reset_at")

        return {
            "source_id": health.source_id,
            "source_url": health.source_url,
            "source_name": health.source_name,
            "status": status_enum.value,
            "consecutive_failures": int(health.consecutive_failures),
            "consecutive_successes": int(health.consecutive_successes),
            "last_attempt": last_attempt.isoformat() if last_attempt else None,
            "last_success": last_success.isoformat() if last_success else None,
            "last_status_code": health.last_status_code,
            "cooldown_until": cooldown_until.isoformat() if cooldown_until else None,
            "rate_limit_reset_at": rate_limit_reset.isoformat() if rate_limit_reset else None,
            "working_bypass_tier": int(health.working_bypass_tier),
        }

    def _row_to_health(self, row: aiosqlite.Row) -> SourceHealth:
        """Reconstruct a SourceHealth domain model from an aiosqlite Row."""
        last_attempt = (
            datetime.fromisoformat(row["last_attempt"]).astimezone(UTC)
            if row["last_attempt"]
            else None
        )
        last_success = (
            datetime.fromisoformat(row["last_success"]).astimezone(UTC)
            if row["last_success"]
            else None
        )
        cooldown_until = (
            datetime.fromisoformat(row["cooldown_until"]).astimezone(UTC)
            if row["cooldown_until"]
            else None
        )
        rate_limit_reset_at = (
            datetime.fromisoformat(row["rate_limit_reset_at"]).astimezone(UTC)
            if row["rate_limit_reset_at"]
            else None
        )

        return SourceHealth(
            source_id=row["source_id"],
            source_url=row["source_url"],
            source_name=row["source_name"],
            status=_parse_status(row["status"]),
            consecutive_failures=int(row["consecutive_failures"]),
            consecutive_successes=int(row["consecutive_successes"]),
            last_attempt=last_attempt,
            last_success=last_success,
            last_status_code=row["last_status_code"],
            cooldown_until=cooldown_until,
            rate_limit_reset_at=rate_limit_reset_at,
            working_bypass_tier=int(row["working_bypass_tier"]),
        )

    async def save_health(self, health: SourceHealth) -> None:
        """
        Upsert a SourceHealth operational state record atomically.
        """
        if not isinstance(health, SourceHealth):
            raise DomainValidationError(f"Expected SourceHealth instance, got {type(health)}")

        await self._ensure_initialized()
        params = self._health_to_params(health)

        upsert_sql = """
        INSERT INTO canonical_source_health (
            source_id, source_url, source_name, status,
            consecutive_failures, consecutive_successes,
            last_attempt, last_success, last_status_code,
            cooldown_until, rate_limit_reset_at, working_bypass_tier,
            updated_at
        ) VALUES (
            :source_id, :source_url, :source_name, :status,
            :consecutive_failures, :consecutive_successes,
            :last_attempt, :last_success, :last_status_code,
            :cooldown_until, :rate_limit_reset_at, :working_bypass_tier,
            strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        )
        ON CONFLICT(source_id) DO UPDATE SET
            source_url = excluded.source_url,
            source_name = excluded.source_name,
            status = excluded.status,
            consecutive_failures = excluded.consecutive_failures,
            consecutive_successes = excluded.consecutive_successes,
            last_attempt = excluded.last_attempt,
            last_success = excluded.last_success,
            last_status_code = excluded.last_status_code,
            cooldown_until = excluded.cooldown_until,
            rate_limit_reset_at = excluded.rate_limit_reset_at,
            working_bypass_tier = excluded.working_bypass_tier,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
        """
        await self.engine.execute(upsert_sql, params)

    async def save_health_batch(self, health_records: Sequence[SourceHealth]) -> int:
        """
        Batch upsert multiple SourceHealth records atomically within a single transaction.
        In case of duplicate source_id within the batch, last-write-wins semantics apply.
        """
        if not health_records:
            return 0

        await self._ensure_initialized()

        upsert_sql = """
        INSERT INTO canonical_source_health (
            source_id, source_url, source_name, status,
            consecutive_failures, consecutive_successes,
            last_attempt, last_success, last_status_code,
            cooldown_until, rate_limit_reset_at, working_bypass_tier,
            updated_at
        ) VALUES (
            :source_id, :source_url, :source_name, :status,
            :consecutive_failures, :consecutive_successes,
            :last_attempt, :last_success, :last_status_code,
            :cooldown_until, :rate_limit_reset_at, :working_bypass_tier,
            strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        )
        ON CONFLICT(source_id) DO UPDATE SET
            source_url = excluded.source_url,
            source_name = excluded.source_name,
            status = excluded.status,
            consecutive_failures = excluded.consecutive_failures,
            consecutive_successes = excluded.consecutive_successes,
            last_attempt = excluded.last_attempt,
            last_success = excluded.last_success,
            last_status_code = excluded.last_status_code,
            cooldown_until = excluded.cooldown_until,
            rate_limit_reset_at = excluded.rate_limit_reset_at,
            working_bypass_tier = excluded.working_bypass_tier,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
        """

        param_list = [self._health_to_params(h) for h in health_records]

        async with self.engine.transaction() as conn:
            await conn.executemany(upsert_sql, param_list)

        return len(health_records)

    async def get_health(self, source_id: str) -> Optional[SourceHealth]:
        """
        Retrieve the current SourceHealth state for a specific source by its source_id.
        """
        await self._ensure_initialized()
        sql = "SELECT * FROM canonical_source_health WHERE source_id = ?;"
        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql, (source_id.strip(),))
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_health(row)

    async def get_all_health(self) -> List[SourceHealth]:
        """
        Retrieve all recorded source health states ordered deterministically by source_id.
        """
        await self._ensure_initialized()
        sql = "SELECT * FROM canonical_source_health ORDER BY source_id ASC;"
        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql)
            rows = await cursor.fetchall()
            return [self._row_to_health(r) for r in rows]

    async def get_health_by_status(self, status: SourceHealthStatus) -> List[SourceHealth]:
        """
        Retrieve all source health records matching a specific SourceHealthStatus.
        """
        await self._ensure_initialized()
        status_enum = _parse_status(status)
        sql = "SELECT * FROM canonical_source_health WHERE status = ? ORDER BY source_id ASC;"
        async with self.engine.connect() as conn:
            cursor = await conn.execute(sql, (status_enum.value,))
            rows = await cursor.fetchall()
            return [self._row_to_health(r) for r in rows]

    async def delete_health(self, source_id: str) -> bool:
        """
        Delete a source health record by source_id. Returns True if deleted, False if not found.
        """
        await self._ensure_initialized()
        sql = "DELETE FROM canonical_source_health WHERE source_id = ?;"
        async with self.engine.transaction() as conn:
            cursor = await conn.execute(sql, (source_id.strip(),))
            return cursor.rowcount > 0
