"""
SQLite Connection Engine & Asynchronous Transaction Manager.
Location: src/storage/sqlite_engine.py

Provides non-blocking, asynchronous SQLite connection management using aiosqlite:
- Strict WAL journal mode, foreign key enforcement, and busy timeout configuration
- Transactional context management with atomic commit and rollback
- Idempotent schema initialization from schema_sqlite.sql
- Bounded and deterministic connection lifecycle management
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional, Sequence, Union

import aiosqlite

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_CANONICAL_DB_PATH: Path = DATA_DIR / "canonical_events.db"
SCHEMA_SQL_PATH: Path = Path(__file__).parent / "schema_sqlite.sql"

# SQLite configuration constants
BUSY_TIMEOUT_MS: int = 10000


class SqliteEngine:
    """
    Asynchronous SQLite Connection Engine.
    
    Manages database lifecycle, PRAGMA enforcement, schema migrations,
    and scoped transaction contexts.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        if db_path is None:
            self.db_path = DEFAULT_CANONICAL_DB_PATH
        else:
            self.db_path = Path(db_path).resolve()

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._is_initialized = False
        self._lock = asyncio.Lock()

    async def _configure_connection(self, conn: aiosqlite.Connection) -> None:
        """Apply mandatory performance and integrity PRAGMAs."""
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode = WAL;")
        await conn.execute("PRAGMA synchronous = NORMAL;")
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};")

    async def initialize_schema(self, schema_file: Optional[Path] = None) -> None:
        """
        Idempotently execute the schema DDL to create all canonical tables and indexes.
        """
        async with self._lock:
            target_schema_path = schema_file or SCHEMA_SQL_PATH
            if not target_schema_path.exists():
                raise FileNotFoundError(f"Schema file not found at {target_schema_path}")

            schema_sql = target_schema_path.read_text(encoding="utf-8")

            async with self.connect() as conn:
                await conn.executescript(schema_sql)
                await conn.commit()

            self._is_initialized = True
            logger.info(f"Canonical SQLite schema initialized successfully at {self.db_path}")

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """
        Context manager providing a configured, non-transactional connection.
        Automatically closes the connection upon context exit.
        """
        conn = await aiosqlite.connect(self.db_path)
        try:
            await self._configure_connection(conn)
            yield conn
        finally:
            await conn.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """
        Context manager providing an atomic transaction.
        Commits on normal exit; automatically rolls back on exception.
        """
        async with self.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE;")
            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def execute(
        self,
        sql: str,
        parameters: Optional[Union[Sequence[Any], Dict[str, Any]]] = None,
    ) -> aiosqlite.Cursor:
        """
        Execute a single parameterized query inside a short-lived transaction.
        """
        async with self.transaction() as conn:
            return await conn.execute(sql, parameters)

    async def executemany(
        self,
        sql: str,
        parameters: Iterable[Union[Sequence[Any], Dict[str, Any]]],
    ) -> aiosqlite.Cursor:
        """
        Execute a batch parameterized query inside a short-lived transaction.
        """
        async with self.transaction() as conn:
            return await conn.executemany(sql, parameters)

    async def fetchone(
        self,
        sql: str,
        parameters: Optional[Union[Sequence[Any], Dict[str, Any]]] = None,
    ) -> Optional[aiosqlite.Row]:
        """
        Execute a query and fetch a single matching row.
        """
        async with self.connect() as conn:
            cursor = await conn.execute(sql, parameters)
            return await cursor.fetchone()

    async def fetchall(
        self,
        sql: str,
        parameters: Optional[Union[Sequence[Any], Dict[str, Any]]] = None,
    ) -> List[aiosqlite.Row]:
        """
        Execute a query and fetch all matching rows.
        """
        async with self.connect() as conn:
            cursor = await conn.execute(sql, parameters)
            return await cursor.fetchall()

    async def aclose(self) -> None:
        """Deterministic cleanup hook."""
        self._is_initialized = False

    async def __aenter__(self) -> aiosqlite.Connection:
        self._ctx_conn = await aiosqlite.connect(self.db_path)
        await self._configure_connection(self._ctx_conn)
        return self._ctx_conn

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if hasattr(self, "_ctx_conn") and self._ctx_conn:
            await self._ctx_conn.close()
            self._ctx_conn = None
