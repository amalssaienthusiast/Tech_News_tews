"""
Swarm Coordinator & Lease-Based Worker Partitioning.
Location: src/zombies/coordinator.py

Defines abstract SwarmCoordinatorProtocol, LocalSwarmCoordinator (in-memory, single-process),
and SqliteSwarmCoordinator (multi-process on same host via dedicated swarm_leases table).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, UTC, timedelta
from enum import Enum
import hashlib
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union
from uuid import uuid4

logger = logging.getLogger(__name__)


class LeaseStatus(str, Enum):
    """Outcomes of a lease acquisition or renewal attempt."""
    ACQUIRED = "acquired"
    ALREADY_OWNED = "already_owned"
    OWNED_BY_OTHER = "owned_by_other"
    EXPIRED_AND_RECLAIMED = "expired_and_reclaimed"
    INVALID_TOKEN = "invalid_token"


@dataclass(frozen=True, slots=True)
class LeaseResult:
    """Immutable result of a lease operation."""
    status: LeaseStatus
    source_id: str
    token: Optional[str]
    lease_owner: Optional[str]
    lease_expiry: Optional[datetime]

    @property
    def is_successful(self) -> bool:
        return self.status in (LeaseStatus.ACQUIRED, LeaseStatus.ALREADY_OWNED, LeaseStatus.EXPIRED_AND_RECLAIMED)


class SwarmCoordinatorProtocol(Protocol):
    """Abstract protocol for worker task partitioning and atomic lease coordination."""

    async def acquire_lease(
        self, source_id: str, worker_id: str, duration_seconds: float = 300.0
    ) -> LeaseResult:
        """Atomically attempt to acquire exclusive lease ownership for a source."""
        ...

    async def renew_lease(
        self, source_id: str, worker_id: str, token: str, duration_seconds: float = 300.0
    ) -> LeaseResult:
        """Renew active lease if and only if worker_id and lease token match."""
        ...

    async def release_lease(self, source_id: str, worker_id: str, token: str) -> bool:
        """Release lease if held by worker_id with matching token."""
        ...

    async def is_lease_valid(self, source_id: str, worker_id: str, token: str) -> bool:
        """Check if lease is currently active and owned by worker with token."""
        ...

    def get_assigned_sources(
        self, all_sources: List[str], total_shards: int, worker_shard_index: int
    ) -> List[str]:
        """Deterministically partition sources using consistent hashing."""
        ...


class LocalSwarmCoordinator:
    """
    In-memory, single-process Swarm Coordinator.
    Thread-safe and async-safe for coordinating workers within a single process.
    """

    def __init__(self):
        self._leases: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def get_assigned_sources(
        self, all_sources: List[str], total_shards: int, worker_shard_index: int
    ) -> List[str]:
        """Consistent hashing source partitioner."""
        if total_shards <= 1:
            return list(all_sources)

        assigned: List[str] = []
        for s_id in all_sources:
            # MD5 consistent hash shard
            h = int(hashlib.md5(s_id.encode("utf-8")).hexdigest(), 16)
            if (h % total_shards) == worker_shard_index:
                assigned.append(s_id)
        return assigned

    async def acquire_lease(
        self, source_id: str, worker_id: str, duration_seconds: float = 300.0
    ) -> LeaseResult:
        async with self._lock:
            now = datetime.now(UTC)
            current = self._leases.get(source_id)

            if current is not None:
                owner = current["owner"]
                token = current["token"]
                expiry = current["expiry"]

                # Already owned by this worker
                if owner == worker_id and expiry > now:
                    return LeaseResult(
                        status=LeaseStatus.ALREADY_OWNED,
                        source_id=source_id,
                        token=token,
                        lease_owner=owner,
                        lease_expiry=expiry,
                    )

                # Owned by other worker and still valid
                if owner != worker_id and expiry > now:
                    return LeaseResult(
                        status=LeaseStatus.OWNED_BY_OTHER,
                        source_id=source_id,
                        token=None,
                        lease_owner=owner,
                        lease_expiry=expiry,
                    )

                # Expired lease, reclaimable
                status = LeaseStatus.EXPIRED_AND_RECLAIMED
            else:
                status = LeaseStatus.ACQUIRED

            new_token = str(uuid4())
            new_expiry = now + timedelta(seconds=duration_seconds)
            self._leases[source_id] = {
                "owner": worker_id,
                "token": new_token,
                "expiry": new_expiry,
            }

            return LeaseResult(
                status=status,
                source_id=source_id,
                token=new_token,
                lease_owner=worker_id,
                lease_expiry=new_expiry,
            )

    async def renew_lease(
        self, source_id: str, worker_id: str, token: str, duration_seconds: float = 300.0
    ) -> LeaseResult:
        async with self._lock:
            now = datetime.now(UTC)
            current = self._leases.get(source_id)

            if current is None:
                return LeaseResult(
                    status=LeaseStatus.INVALID_TOKEN,
                    source_id=source_id,
                    token=None,
                    lease_owner=None,
                    lease_expiry=None,
                )

            if current["owner"] != worker_id or current["token"] != token:
                return LeaseResult(
                    status=LeaseStatus.INVALID_TOKEN,
                    source_id=source_id,
                    token=None,
                    lease_owner=current["owner"],
                    lease_expiry=current["expiry"],
                )

            new_expiry = now + timedelta(seconds=duration_seconds)
            current["expiry"] = new_expiry

            return LeaseResult(
                status=LeaseStatus.ACQUIRED,
                source_id=source_id,
                token=token,
                lease_owner=worker_id,
                lease_expiry=new_expiry,
            )

    async def release_lease(self, source_id: str, worker_id: str, token: str) -> bool:
        async with self._lock:
            current = self._leases.get(source_id)
            if current and current["owner"] == worker_id and current["token"] == token:
                del self._leases[source_id]
                return True
            return False

    async def is_lease_valid(self, source_id: str, worker_id: str, token: str) -> bool:
        async with self._lock:
            now = datetime.now(UTC)
            current = self._leases.get(source_id)
            if current and current["owner"] == worker_id and current["token"] == token and current["expiry"] > now:
                return True
            return False


class SqliteSwarmCoordinator:
    """
    Multi-Process Swarm Coordinator backed by SQLite.
    Allows independent OS processes to coordinate exclusive source leases
    using atomic transactions and fencing tokens on a shared coordinator database.
    """

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        import sqlite3
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS swarm_leases (
                    source_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    token TEXT NOT NULL,
                    expiry_epoch REAL NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_swarm_leases_expiry ON swarm_leases(expiry_epoch);")
        finally:
            conn.close()

    def get_assigned_sources(
        self, all_sources: List[str], total_shards: int, worker_shard_index: int
    ) -> List[str]:
        """Consistent hashing source partitioner."""
        if total_shards <= 1:
            return list(all_sources)

        assigned: List[str] = []
        for s_id in all_sources:
            h = int(hashlib.md5(s_id.encode("utf-8")).hexdigest(), 16)
            if (h % total_shards) == worker_shard_index:
                assigned.append(s_id)
        return assigned

    def _sync_acquire_lease(
        self, source_id: str, worker_id: str, duration_seconds: float
    ) -> LeaseResult:
        import sqlite3
        now_epoch = time.time()
        new_expiry_epoch = now_epoch + duration_seconds
        new_token = str(uuid4())
        new_expiry_dt = datetime.fromtimestamp(new_expiry_epoch, tz=UTC)

        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute(
                "SELECT worker_id, token, expiry_epoch FROM swarm_leases WHERE source_id = ?;",
                (source_id,),
            )
            row = cursor.fetchone()

            if row is not None:
                curr_owner = row["worker_id"]
                curr_token = row["token"]
                curr_expiry_epoch = row["expiry_epoch"]
                curr_expiry_dt = datetime.fromtimestamp(curr_expiry_epoch, tz=UTC)

                if curr_owner == worker_id and curr_expiry_epoch > now_epoch:
                    conn.execute("COMMIT;")
                    return LeaseResult(
                        status=LeaseStatus.ALREADY_OWNED,
                        source_id=source_id,
                        token=curr_token,
                        lease_owner=curr_owner,
                        lease_expiry=curr_expiry_dt,
                    )

                if curr_owner != worker_id and curr_expiry_epoch > now_epoch:
                    conn.execute("COMMIT;")
                    return LeaseResult(
                        status=LeaseStatus.OWNED_BY_OTHER,
                        source_id=source_id,
                        token=None,
                        lease_owner=curr_owner,
                        lease_expiry=curr_expiry_dt,
                    )

                # Lease expired: reclaim
                status = LeaseStatus.EXPIRED_AND_RECLAIMED
            else:
                status = LeaseStatus.ACQUIRED

            conn.execute(
                """
                INSERT INTO swarm_leases(source_id, worker_id, token, expiry_epoch)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    worker_id = excluded.worker_id,
                    token = excluded.token,
                    expiry_epoch = excluded.expiry_epoch;
                """,
                (source_id, worker_id, new_token, new_expiry_epoch),
            )
            conn.execute("COMMIT;")

            return LeaseResult(
                status=status,
                source_id=source_id,
                token=new_token,
                lease_owner=worker_id,
                lease_expiry=new_expiry_dt,
            )
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def _sync_renew_lease(
        self, source_id: str, worker_id: str, token: str, duration_seconds: float
    ) -> LeaseResult:
        now_epoch = time.time()
        new_expiry_epoch = now_epoch + duration_seconds
        new_expiry_dt = datetime.fromtimestamp(new_expiry_epoch, tz=UTC)

        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute(
                "SELECT worker_id, token, expiry_epoch FROM swarm_leases WHERE source_id = ?;",
                (source_id,),
            )
            row = cursor.fetchone()

            if row is None or row["worker_id"] != worker_id or row["token"] != token:
                conn.execute("COMMIT;")
                return LeaseResult(
                    status=LeaseStatus.INVALID_TOKEN,
                    source_id=source_id,
                    token=None,
                    lease_owner=row["worker_id"] if row else None,
                    lease_expiry=datetime.fromtimestamp(row["expiry_epoch"], tz=UTC) if row else None,
                )

            conn.execute(
                "UPDATE swarm_leases SET expiry_epoch = ? WHERE source_id = ? AND worker_id = ? AND token = ?;",
                (new_expiry_epoch, source_id, worker_id, token),
            )
            conn.execute("COMMIT;")

            return LeaseResult(
                status=LeaseStatus.ACQUIRED,
                source_id=source_id,
                token=token,
                lease_owner=worker_id,
                lease_expiry=new_expiry_dt,
            )
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def _sync_release_lease(self, source_id: str, worker_id: str, token: str) -> bool:
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute(
                "DELETE FROM swarm_leases WHERE source_id = ? AND worker_id = ? AND token = ?;",
                (source_id, worker_id, token),
            )
            changes = conn.total_changes
            conn.execute("COMMIT;")
            return cursor.rowcount > 0
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def _sync_is_lease_valid(self, source_id: str, worker_id: str, token: str) -> bool:
        now_epoch = time.time()
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT 1 FROM swarm_leases WHERE source_id = ? AND worker_id = ? AND token = ? AND expiry_epoch > ?;",
                (source_id, worker_id, token, now_epoch),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    async def acquire_lease(
        self, source_id: str, worker_id: str, duration_seconds: float = 300.0
    ) -> LeaseResult:
        return await asyncio.to_thread(self._sync_acquire_lease, source_id, worker_id, duration_seconds)

    async def renew_lease(
        self, source_id: str, worker_id: str, token: str, duration_seconds: float = 300.0
    ) -> LeaseResult:
        return await asyncio.to_thread(self._sync_renew_lease, source_id, worker_id, token, duration_seconds)

    async def release_lease(self, source_id: str, worker_id: str, token: str) -> bool:
        return await asyncio.to_thread(self._sync_release_lease, source_id, worker_id, token)

    async def is_lease_valid(self, source_id: str, worker_id: str, token: str) -> bool:
        return await asyncio.to_thread(self._sync_is_lease_valid, source_id, worker_id, token)
