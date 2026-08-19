"""
Authentication Manager & API Key Lifecycle.
Location: src/security/auth_manager.py
"""

from __future__ import annotations

from datetime import datetime, UTC
import hmac
import logging
import os
from typing import Dict, List, Optional, Protocol, Set, Tuple, runtime_checkable

from .models import (
    ApiKeyMetadata,
    Principal,
    Role,
    STANDARD_SCOPES,
    hash_key_fingerprint,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class AuthManagerProtocol(Protocol):
    """Abstract authentication management interface."""

    def authenticate_key(self, raw_key: str) -> Optional[Principal]:
        """Authenticate a raw API key and return authenticated Principal if valid."""
        ...

    def get_principal_by_fingerprint(self, fingerprint: str) -> Optional[Principal]:
        """Look up active principal metadata by key fingerprint."""
        ...


class EnvAuthManager(AuthManagerProtocol):
    """
    In-memory and environment-backed authentication manager.
    
    Provides constant-time HMAC key verification and lifecycle management
    (enabled/disabled, expiration, roles, granular scopes).
    """

    def __init__(self, admin_key_env_var: str = "TECHNEWS_ADMIN_KEY") -> None:
        self.admin_key_env_var = admin_key_env_var
        self._keys: Dict[str, Tuple[str, ApiKeyMetadata]] = {}  # fingerprint -> (raw_key, metadata)
        self._load_from_environment()

    def _load_from_environment(self) -> None:
        """Load default keys from environment variables."""
        admin_key = os.getenv(self.admin_key_env_var) or os.getenv("TECHNEWS_ADMIN_API_KEY")
        if admin_key and admin_key.strip():
            self.register_key(
                raw_key=admin_key.strip(),
                identity="system_admin",
                role=Role.ADMIN,
            )

        rw_key = os.getenv("TECHNEWS_RW_API_KEY") or os.getenv("TECHNEWS_RW_KEY")
        if rw_key and rw_key.strip():
            self.register_key(
                raw_key=rw_key.strip(),
                identity="ingestion_service",
                role=Role.READ_WRITE,
            )

        ro_key = os.getenv("TECHNEWS_RO_API_KEY") or os.getenv("TECHNEWS_RO_KEY")
        if ro_key and ro_key.strip():
            self.register_key(
                raw_key=ro_key.strip(),
                identity="reader_client",
                role=Role.READ_ONLY,
            )

    def register_key(
        self,
        raw_key: str,
        identity: str,
        role: Role,
        scopes: Optional[Set[str]] = None,
        expires_at: Optional[datetime] = None,
    ) -> ApiKeyMetadata:
        """
        Register a new API key with associated role, scopes, and expiration.
        """
        if not raw_key or not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("API key cannot be empty")

        clean_key = raw_key.strip()
        fingerprint = hash_key_fingerprint(clean_key)
        assigned_scopes = frozenset(scopes) if scopes is not None else STANDARD_SCOPES.get(role, frozenset())

        metadata = ApiKeyMetadata(
            fingerprint=fingerprint,
            identity=identity,
            role=role,
            scopes=assigned_scopes,
            enabled=True,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        self._keys[fingerprint] = (clean_key, metadata)
        logger.info(f"Registered API key for identity='{identity}', role='{role.value}', fingerprint='{fingerprint}'")
        return metadata

    def authenticate_key(self, raw_key: str) -> Optional[Principal]:
        """
        Authenticate raw API key in constant time across all registered credentials.
        """
        if not raw_key or not isinstance(raw_key, str):
            return None

        clean_key = raw_key.strip()
        target_fingerprint = hash_key_fingerprint(clean_key)
        matched_metadata: Optional[ApiKeyMetadata] = None

        # Check candidate by fingerprint first, then constant-time compare
        if target_fingerprint in self._keys:
            stored_key, meta = self._keys[target_fingerprint]
            if hmac.compare_digest(stored_key.encode("utf-8"), clean_key.encode("utf-8")):
                if meta.is_valid_at():
                    matched_metadata = meta

        if matched_metadata is None:
            return None

        return Principal(
            identity=matched_metadata.identity,
            role=matched_metadata.role,
            scopes=matched_metadata.scopes,
            api_key_fingerprint=matched_metadata.fingerprint,
            is_authenticated=True,
        )

    def get_principal_by_fingerprint(self, fingerprint: str) -> Optional[Principal]:
        """Retrieve principal by fingerprint without key verification."""
        if fingerprint in self._keys:
            _, meta = self._keys[fingerprint]
            if meta.is_valid_at():
                return Principal(
                    identity=meta.identity,
                    role=meta.role,
                    scopes=meta.scopes,
                    api_key_fingerprint=meta.fingerprint,
                    is_authenticated=True,
                )
        return None

    def revoke_key(self, fingerprint: str) -> bool:
        """Disable an API key by fingerprint."""
        if fingerprint in self._keys:
            raw_key, meta = self._keys[fingerprint]
            disabled_meta = ApiKeyMetadata(
                fingerprint=meta.fingerprint,
                identity=meta.identity,
                role=meta.role,
                scopes=meta.scopes,
                enabled=False,
                created_at=meta.created_at,
                expires_at=meta.expires_at,
            )
            self._keys[fingerprint] = (raw_key, disabled_meta)
            return True
        return False
