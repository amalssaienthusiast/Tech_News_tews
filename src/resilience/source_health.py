"""
Source health monitoring for news sources.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class SourceStatus(Enum):
    """Health status of a news source."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class SourceHealthRecord:
    """Health record for a single source."""
    source_name: str
    status: SourceStatus
    last_checked: datetime
    success_rate: float  # 0.0 to 1.0
    avg_response_time_ms: float
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    articles_last_fetch: int = 0


@dataclass  
class HealthCheckResult:
    """Result of a health check."""
    source_name: str
    success: bool
    response_time_ms: float
    articles_found: int
    error: Optional[str] = None


class SourceHealthMonitor:
    """
    Monitors the health of news sources:
    - Tracks success/failure rates
    - Detects degraded sources
    - Provides health reports
    """
    
    def __init__(self):
        self.source_health: Dict[str, SourceHealthRecord] = {}
        self.check_history: Dict[str, List[HealthCheckResult]] = {}
        self._initialized = False
        
        # Configuration
        self.degraded_threshold = 0.7  # Below 70% success = degraded
        self.unhealthy_threshold = 0.3  # Below 30% success = unhealthy
        self.max_history_per_source = 100
        
    async def initialize(self) -> None:
        """Initialize the source health monitor."""
        if self._initialized:
            return
        
        self._initialized = True
        logger.info("SourceHealthMonitor initialized")
    
    def record_check(self, result: HealthCheckResult) -> None:
        """Record a health check result."""
        source = result.source_name
        
        # Initialize history if needed
        if source not in self.check_history:
            self.check_history[source] = []
        
        # Add to history
        self.check_history[source].append(result)
        
        # Trim history
        if len(self.check_history[source]) > self.max_history_per_source:
            self.check_history[source] = self.check_history[source][-self.max_history_per_source:]
        
        # Update health record
        self._update_health_record(source)
    
    def _update_health_record(self, source: str) -> None:
        """Update health record based on check history."""
        history = self.check_history.get(source, [])
        
        if not history:
            return
        
        # Calculate metrics
        successes = sum(1 for h in history if h.success)
        success_rate = successes / len(history)
        
        avg_response_time = sum(h.response_time_ms for h in history) / len(history)
        
        # Count consecutive failures
        consecutive_failures = 0
        for h in reversed(history):
            if not h.success:
                consecutive_failures += 1
            else:
                break
        
        # Determine status
        if consecutive_failures >= 5:
            status = SourceStatus.UNHEALTHY
        elif success_rate < self.unhealthy_threshold:
            status = SourceStatus.UNHEALTHY
        elif success_rate < self.degraded_threshold:
            status = SourceStatus.DEGRADED
        else:
            status = SourceStatus.HEALTHY
        
        # Get last error
        last_error = None
        for h in reversed(history):
            if h.error:
                last_error = h.error
                break
        
        # Get articles from last successful fetch
        articles_last = 0
        for h in reversed(history):
            if h.success:
                articles_last = h.articles_found
                break
        
        self.source_health[source] = SourceHealthRecord(
            source_name=source,
            status=status,
            last_checked=datetime.now(timezone.utc),
            success_rate=success_rate,
            avg_response_time_ms=avg_response_time,
            last_error=last_error,
            consecutive_failures=consecutive_failures,
            articles_last_fetch=articles_last
        )
    
    async def check_all_sources(self) -> Dict[str, Any]:
        """Check all monitored sources and return summary."""
        summary: Dict[str, Any] = {
            'total_sources': len(self.source_health),
            'healthy_sources': [],
            'degraded_sources': [],
            'unhealthy_sources': [],
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        for source, record in self.source_health.items():
            if record.status == SourceStatus.HEALTHY:
                summary['healthy_sources'].append(source)
            elif record.status == SourceStatus.DEGRADED:
                summary['degraded_sources'].append(source)
            else:
                summary['unhealthy_sources'].append(source)
        
        return summary
    
    def get_summary_report(self) -> Dict[str, Any]:
        """Get summary health report."""
        healthy = sum(1 for r in self.source_health.values() 
                     if r.status == SourceStatus.HEALTHY)
        degraded = sum(1 for r in self.source_health.values() 
                      if r.status == SourceStatus.DEGRADED)
        unhealthy = sum(1 for r in self.source_health.values() 
                       if r.status == SourceStatus.UNHEALTHY)
        
        return {
            'total': len(self.source_health),
            'healthy': healthy,
            'degraded': degraded,
            'unhealthy': unhealthy,
            'overall_status': 'healthy' if unhealthy == 0 else ('degraded' if healthy > unhealthy else 'unhealthy')
        }
    
    def get_detailed_report(self) -> Dict[str, Any]:
        """Get detailed per-source health info."""
        return {
            source: {
                'status': record.status.value,
                'success_rate': f"{record.success_rate:.1%}",
                'avg_response_time': f"{record.avg_response_time_ms:.0f}ms",
                'consecutive_failures': record.consecutive_failures,
                'last_error': record.last_error,
                'articles_last_fetch': record.articles_last_fetch,
                'last_checked': record.last_checked.isoformat()
            }
            for source, record in self.source_health.items()
        }
    
    def get_source_status(self, source: str) -> Optional[SourceStatus]:
        """Get status of a specific source."""
        record = self.source_health.get(source)
        return record.status if record else None
    
    def mark_source_healthy(self, source: str) -> None:
        """Manually mark a source as healthy (after manual fix)."""
        if source in self.source_health:
            self.source_health[source].status = SourceStatus.HEALTHY
            self.source_health[source].consecutive_failures = 0
            logger.info(f"Source {source} manually marked as healthy")
