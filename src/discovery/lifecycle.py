"""
Source Discovery Lifecycle State Machine with Rejection Quarantine.
Location: src/discovery/lifecycle.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class DiscoveryState(str, Enum):
    """Lifecycle states for candidate source discovery."""
    DISCOVERED = "discovered"
    VETTING = "vetting"
    QUARANTINED = "quarantined"
    PROMOTED = "promoted"
    RETRY_LATER = "retry_later"
    REJECTED_PERMANENT = "rejected_permanent"


class InvalidDiscoveryTransitionError(Exception):
    """Raised when an illegal FSM transition is attempted."""
    pass


@dataclass(frozen=True, slots=True)
class DiscoveredSourceRecord:
    """Immutable state snapshot for a candidate discovered source."""
    source_url: str
    state: DiscoveryState
    discovered_at: datetime
    updated_at: datetime
    discovery_method: str = "web_search"
    test_runs_completed: int = 0
    test_runs_passed: int = 0
    rejection_reason: Optional[str] = None
    next_retry_at: Optional[datetime] = None


class DiscoveryLifecycleManager:
    """
    Manages the lifecycle of discovered tech news candidate sources.
    Maintains a permanent rejection registry to prevent rediscovery loops,
    and supports transient retry backoff without polluting permanent blacklists.
    """

    # Valid FSM transitions
    VALID_TRANSITIONS: Dict[DiscoveryState, Set[DiscoveryState]] = {
        DiscoveryState.DISCOVERED: {
            DiscoveryState.VETTING,
            DiscoveryState.REJECTED_PERMANENT,
        },
        DiscoveryState.VETTING: {
            DiscoveryState.QUARANTINED,
            DiscoveryState.RETRY_LATER,
            DiscoveryState.REJECTED_PERMANENT,
        },
        DiscoveryState.QUARANTINED: {
            DiscoveryState.PROMOTED,
            DiscoveryState.RETRY_LATER,
            DiscoveryState.REJECTED_PERMANENT,
        },
        DiscoveryState.RETRY_LATER: {
            DiscoveryState.VETTING,
            DiscoveryState.REJECTED_PERMANENT,
        },
        DiscoveryState.PROMOTED: set(),  # Terminal in discovery lifecycle (handover to SourceHealthRepository)
        DiscoveryState.REJECTED_PERMANENT: set(),  # Permanent terminal state
    }

    def __init__(self, quarantine_required_passes: int = 3, retry_cooldown_minutes: int = 60):
        self.quarantine_required_passes = quarantine_required_passes
        self.retry_cooldown_minutes = retry_cooldown_minutes
        self._sources: Dict[str, DiscoveredSourceRecord] = {}
        self._permanent_rejections: Set[str] = set()

    def is_permanently_rejected(self, url: str) -> bool:
        """Check if URL is in permanent rejection blacklist."""
        clean_url = url.strip().lower()
        return clean_url in self._permanent_rejections

    def register_discovered(
        self,
        url: str,
        discovery_method: str = "web_search",
    ) -> DiscoveredSourceRecord:
        """Register a newly discovered candidate URL."""
        clean_url = url.strip()
        clean_key = clean_url.lower()

        if clean_key in self._permanent_rejections:
            raise InvalidDiscoveryTransitionError(f"URL '{clean_url}' is permanently rejected")

        if clean_key in self._sources:
            return self._sources[clean_key]

        now = datetime.now(UTC)
        record = DiscoveredSourceRecord(
            source_url=clean_url,
            state=DiscoveryState.DISCOVERED,
            discovered_at=now,
            updated_at=now,
            discovery_method=discovery_method,
        )
        self._sources[clean_key] = record
        return record

    def transition(
        self,
        url: str,
        target_state: DiscoveryState,
        reason: Optional[str] = None,
        test_passed: Optional[bool] = None,
    ) -> DiscoveredSourceRecord:
        """Transition discovered source to a new state."""
        clean_key = url.strip().lower()
        current = self._sources.get(clean_key)

        if current is None:
            raise InvalidDiscoveryTransitionError(f"Cannot transition unknown discovered source '{url}'")

        allowed_targets = self.VALID_TRANSITIONS.get(current.state, set())
        if target_state not in allowed_targets:
            raise InvalidDiscoveryTransitionError(
                f"Invalid discovery transition from {current.state.value} to {target_state.value} for '{url}'"
            )

        now = datetime.now(UTC)
        test_runs = current.test_runs_completed + (1 if test_passed is not None else 0)
        passes = current.test_runs_passed + (1 if test_passed is True else 0)

        next_retry = None
        if target_state == DiscoveryState.RETRY_LATER:
            next_retry = now + timedelta(minutes=self.retry_cooldown_minutes)

        if target_state == DiscoveryState.REJECTED_PERMANENT:
            self._permanent_rejections.add(clean_key)

        new_record = DiscoveredSourceRecord(
            source_url=current.source_url,
            state=target_state,
            discovered_at=current.discovered_at,
            updated_at=now,
            discovery_method=current.discovery_method,
            test_runs_completed=test_runs,
            test_runs_passed=passes,
            rejection_reason=reason or current.rejection_reason,
            next_retry_at=next_retry,
        )
        self._sources[clean_key] = new_record
        return new_record

    def get_source(self, url: str) -> Optional[DiscoveredSourceRecord]:
        return self._sources.get(url.strip().lower())
