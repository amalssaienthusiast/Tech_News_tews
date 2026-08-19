"""
Phase 8E: Operational Soak & Data Integrity Unit Tests.
Location: tests/test_operational_soak.py

Tests:
1. ObservationLedger strict mathematical conservation invariant.
2. Silent data-loss detection on missing/unaccounted items.
3. FTS5 stratified search latency sampler.
4. Operational soak telemetry monitor & FD invariance.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from pathlib import Path
import tempfile
import time

import pytest

from benchmarks.benchmark_operational_soak import (
    ObservationLedger,
    OperationalSoakHarness,
)
from src.domain.enums import SourceTier, ZombieSpecies
from src.domain.models import SourceObservation
from src.pipeline.runner import CanonicalPipelineRunner
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_event_repository import SqliteEventRepository


def test_observation_ledger_conservation_invariant():
    """Verify generated = persisted + rejected + dropped + in_flight, with zero data loss."""
    ledger = ObservationLedger()
    ledger.record_generated(100)
    assert ledger.in_flight_count == 100
    assert ledger.silent_data_loss == 0

    ledger.record_persisted(70)
    ledger.record_rejected(15)
    ledger.record_dropped(15)

    assert ledger.in_flight_count == 0
    assert ledger.silent_data_loss == 0
    assert ledger.persisted_count == 70
    assert ledger.explicitly_rejected_count == 15
    assert ledger.explicitly_dropped_count == 15


def test_observation_ledger_detects_silent_loss():
    """Verify ledger detects when an observation is generated but unaccounted for."""
    ledger = ObservationLedger()
    ledger.record_generated(50)
    ledger.record_persisted(40)
    # 10 items in flight
    assert ledger.silent_data_loss == 0

    # Simulate dropped/leaked in_flight items
    ledger.in_flight_count = 0 # Leaked without record_persisted/rejected/dropped
    assert ledger.silent_data_loss == 10


@pytest.mark.asyncio
async def test_operational_soak_e1_smoke_run():
    """Verify Regime E1 execution satisfies all hard invariants and produces zero data loss."""
    harness = OperationalSoakHarness()
    report = await harness.execute_regime(
        regime_name="E1_Smoke_Operational_Lifecycle",
        duration_seconds=5.0,
        base_offered_rate=30.0,
        checkpoint_interval_seconds=2.0,
        mode="calibrated_smoke_harness",
    )

    assert report.status == "PASS"
    assert report.duration_valid is True
    assert report.silent_data_loss == 0
    assert report.total_persisted > 0
    assert abs(report.fd_delta) <= 2
    assert report.sqlite_busy_errors == 0
    assert len(report.checkpoints) >= 2
