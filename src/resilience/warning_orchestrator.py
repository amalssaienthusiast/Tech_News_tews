"""
Warning aggregation and suppression system.
"""

from __future__ import annotations

import warnings
import logging
import re
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class WarningRecord:
    """Record of a warning occurrence."""
    message: str
    category: str
    source: str
    count: int
    first_seen: datetime
    last_seen: datetime


class WarningOrchestrator:
    """
    Orchestrates warning handling:
    - Aggregates similar warnings
    - Suppresses known warnings
    - Tracks warning patterns
    """
    
    def __init__(self):
        self.warnings: Dict[str, WarningRecord] = {}
        self.suppressed_patterns: Set[str] = set()
        self._lock = Lock()
        self._initialized = False
        
        # Configuration
        self.suppression_window_seconds = 300  # 5 minutes
        self.max_warnings_per_source = 100
        
        # Known suppressions
        self._known_suppressions = [
            r'To avoid breaking existing software while fixing issue 310',
            r'This package.*has been renamed to',
            r'duckduckgo.*deprecated',
            r'feedparser.*DeprecationWarning',
        ]
    
    async def initialize(self) -> None:
        """Initialize the warning orchestrator."""
        if self._initialized:
            return
        
        # Apply known suppressions
        self._apply_known_suppressions()
        
        self._initialized = True
        logger.info("WarningOrchestrator initialized")
    
    def _apply_known_suppressions(self) -> None:
        """Apply all known warning suppressions."""
        for pattern in self._known_suppressions:
            self._suppress_pattern(pattern)
            self.suppressed_patterns.add(pattern)
    
    def _suppress_pattern(self, pattern: str) -> None:
        """Suppress warnings matching a pattern."""
        try:
            warnings.filterwarnings("ignore", message=pattern)
            logger.debug(f"Suppressed warning pattern: {pattern}")
        except Exception as e:
            logger.error(f"Failed to suppress pattern {pattern}: {e}")
    
    def add_suppression(self, pattern: str) -> None:
        """Add a new warning suppression pattern."""
        with self._lock:
            if pattern not in self.suppressed_patterns:
                self._suppress_pattern(pattern)
                self.suppressed_patterns.add(pattern)
    
    def record_warning(self, message: str, category: str = 'Unknown', 
                       source: str = 'Unknown') -> None:
        """Record a warning occurrence."""
        with self._lock:
            # Create a hash key for this warning type
            key = f"{category}:{message[:50]}"
            
            now = datetime.now(timezone.utc)
            
            if key in self.warnings:
                # Update existing record
                record = self.warnings[key]
                record.count += 1
                record.last_seen = now
            else:
                # Create new record
                self.warnings[key] = WarningRecord(
                    message=message,
                    category=category,
                    source=source,
                    count=1,
                    first_seen=now,
                    last_seen=now
                )
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of warnings."""
        with self._lock:
            total_warnings = sum(w.count for w in self.warnings.values())
            unique_warnings = len(self.warnings)
            
            # Get top warnings by count
            top_warnings = sorted(
                self.warnings.values(),
                key=lambda w: w.count,
                reverse=True
            )[:10]
            
            return {
                'total_warnings': total_warnings,
                'unique_warnings': unique_warnings,
                'suppressed_patterns': len(self.suppressed_patterns),
                'top_warnings': [
                    {
                        'message': w.message[:100],
                        'category': w.category,
                        'count': w.count,
                        'first_seen': w.first_seen.isoformat(),
                        'last_seen': w.last_seen.isoformat()
                    }
                    for w in top_warnings
                ]
            }
    
    def clear_old_warnings(self, older_than_hours: int = 24) -> int:
        """Clear warnings older than specified hours."""
        with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
            
            old_keys = [
                key for key, record in self.warnings.items()
                if record.last_seen < cutoff
            ]
            
            for key in old_keys:
                del self.warnings[key]
            
            return len(old_keys)
    
    def get_pattern_matches(self, pattern: str) -> List[WarningRecord]:
        """Get warnings matching a pattern."""
        with self._lock:
            matches = []
            regex = re.compile(pattern, re.IGNORECASE)
            
            for record in self.warnings.values():
                if regex.search(record.message):
                    matches.append(record)
            
            return matches
    
    def suppress_all_current(self) -> int:
        """Suppress all currently tracked warning patterns."""
        with self._lock:
            count = 0
            for record in self.warnings.values():
                pattern = re.escape(record.message[:50])
                if pattern not in self.suppressed_patterns:
                    self._suppress_pattern(pattern)
                    self.suppressed_patterns.add(pattern)
                    count += 1
            
            return count
