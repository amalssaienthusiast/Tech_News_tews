"""
Security Domain Models & Data Structures.
Location: src/security/models.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
import hashlib
from typing import FrozenSet, Optional, Set


class Role(str, Enum):
    """Hierarchical Security Roles."""
    ADMIN = "admin"
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"
    ANONYMOUS = "anonymous"

    @property
    def rank(self) -> int:
        """Higher integer denotes higher privilege level."""
        ranks = {
            Role.ANONYMOUS: 0,
            Role.READ_ONLY: 1,
            Role.READ_WRITE: 2,
            Role.ADMIN: 3,
        }
        return ranks.get(self, 0)

    def satisfies(self, required_role: Role) -> bool:
        """Check if this role meets or exceeds required_role."""
        return self.rank >= required_role.rank


# Default granular permission scopes
STANDARD_SCOPES: dict[Role, FrozenSet[str]] = {
    Role.ADMIN: frozenset({
        "articles:read",
        "articles:write",
        "articles:search",
        "events:read",
        "events:write",
        "user:read",
        "user:write",
        "system:metrics",
        "system:admin",
    }),
    Role.READ_WRITE: frozenset({
        "articles:read",
        "articles:write",
        "articles:search",
        "events:read",
        "events:write",
        "user:read",
        "user:write",
    }),
    Role.READ_ONLY: frozenset({
        "articles:read",
        "articles:search",
        "events:read",
        "user:read",
    }),
    Role.ANONYMOUS: frozenset({
        "articles:read",
        "events:read",
    }),
}


def hash_key_fingerprint(raw_key: str) -> str:
    """Generate deterministic SHA-256 fingerprint for audit and indexing."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class ApiKeyMetadata:
    """
    Metadata describing an authorized API key without exposing plaintext secret.
    """
    fingerprint: str
    identity: str
    role: Role
    scopes: FrozenSet[str] = field(default_factory=frozenset)
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: Optional[datetime] = None

    def is_valid_at(self, now: Optional[datetime] = None) -> bool:
        """Check if key is currently active and not expired."""
        if not self.enabled:
            return False
        if self.expires_at is None:
            return True
        current = now or datetime.now(UTC)
        return current <= self.expires_at


@dataclass(frozen=True, slots=True)
class Principal:
    """
    Authenticated security principal representing an acting user or system client.
    """
    identity: str
    role: Role
    scopes: FrozenSet[str] = field(default_factory=frozenset)
    api_key_fingerprint: Optional[str] = None
    is_authenticated: bool = False

    def has_scope(self, scope: str) -> bool:
        """Check if principal has required scope or is admin."""
        if self.role == Role.ADMIN:
            return True
        return scope in self.scopes

    @classmethod
    def anonymous(cls) -> Principal:
        """Default unauthenticated principal."""
        return cls(
            identity="anonymous",
            role=Role.ANONYMOUS,
            scopes=STANDARD_SCOPES[Role.ANONYMOUS],
            is_authenticated=False,
        )


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Outcome of a rate limit consumption check."""
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: float
    retry_after: Optional[int] = None
