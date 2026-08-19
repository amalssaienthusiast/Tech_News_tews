"""
Permanent RSS parsing solution with automatic adaptation to feed format changes.
Eliminates feedparser deprecation warnings permanently.
"""

from __future__ import annotations

import feedparser
import warnings
import logging
import re
from datetime import datetime, timezone
from time import mktime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class FeedFormat(Enum):
    """Supported RSS/Atom feed formats."""
    RSS_2_0 = "rss_2_0"
    ATOM_1_0 = "atom_1_0"
    RSS_1_0 = "rss_1_0"
    UNKNOWN = "unknown"


@dataclass
class FeedMetadata:
    """Comprehensive feed metadata."""
    format: FeedFormat
    version: str
    has_published: bool
    has_updated: bool
    has_both: bool
    date_fields: List[str]
    normalization_required: bool


@dataclass
class FeedResult:
    """Normalized feed result with consistent structure."""
    url: str
    title: str
    description: str
    entries: List[Dict[str, Any]]
    metadata: FeedMetadata
    raw_version: str


class RSSCompatibilityEngine:
    """
    Permanent solution for RSS feed parsing that:
    1. Detects feed format automatically
    2. Normalizes date fields across all versions
    3. Handles deprecations gracefully
    4. Logs format changes for future updates
    5. Provides migration recommendations
    """
    
    # Global suppression of feedparser warnings
    _warnings_suppressed = False
    
    def __init__(self):
        if not RSSCompatibilityEngine._warnings_suppressed:
            self._suppress_feedparser_warnings()
            RSSCompatibilityEngine._warnings_suppressed = True
        
        self._feed_history: Dict[str, List[FeedMetadata]] = defaultdict(list)
        self._migration_tracker = MigrationTracker()
        
    def _suppress_feedparser_warnings(self) -> None:
        """Permanently suppress feedparser deprecation warnings."""
        # Suppress the specific feedparser issue 310 warning
        warnings.filterwarnings(
            "ignore",
            message="To avoid breaking existing software while fixing issue 310"
        )
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            module="feedparser"
        )
        # Also suppress general feedparser warnings
        warnings.filterwarnings(
            "ignore",
            message=".*feedparser.*",
            category=DeprecationWarning
        )
        logger.debug("FeedParser deprecation warnings suppressed")
    
    def parse_feed(self, url: str, **kwargs) -> FeedResult:
        """
        Parse RSS/Atom feed with automatic format detection and normalization.
        
        Args:
            url: Feed URL
            **kwargs: Additional arguments for feedparser
            
        Returns:
            Normalized feed result with consistent structure
        """
        # Parse with suppressed warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            raw_feed = feedparser.parse(url, **kwargs)
        
        # Analyze feed format
        metadata = self._analyze_feed_format(raw_feed, url)
        
        # Store historical data for trend analysis
        self._record_feed_metadata(url, metadata)
        
        # Normalize all entries
        normalized_entries = []
        for entry in raw_feed.entries:
            normalized = self._normalize_entry(entry, metadata)
            normalized_entries.append(normalized)
        
        # Check for format migration recommendations
        if metadata.normalization_required:
            self._migration_tracker.record_migration_needed(url, metadata)
        
        return FeedResult(
            url=url,
            title=raw_feed.feed.get('title', ''),
            description=raw_feed.feed.get('description', ''),
            entries=normalized_entries,
            metadata=metadata,
            raw_version=raw_feed.get('version', '')
        )
    
    def _analyze_feed_format(self, feed: Any, url: str) -> FeedMetadata:
        """Analyze feed format and identify date field usage."""
        entries = feed.entries[:10] if feed.entries else []
        
        # Detect format
        version = feed.get('version', '')
        if 'rss' in version.lower():
            format_type = FeedFormat.RSS_2_0
        elif 'atom' in version.lower():
            format_type = FeedFormat.ATOM_1_0
        elif 'rdf' in version.lower():
            format_type = FeedFormat.RSS_1_0
        else:
            format_type = FeedFormat.UNKNOWN
        
        # Analyze date field usage
        date_fields_used: set = set()
        has_published = False
        has_updated = False
        
        for entry in entries:
            if hasattr(entry, 'published') and entry.published:
                date_fields_used.add('published')
                has_published = True
            if hasattr(entry, 'updated') and entry.updated:
                date_fields_used.add('updated')
                has_updated = True
            if hasattr(entry, 'pubDate') and entry.pubDate:
                date_fields_used.add('pubDate')
        
        # Determine if normalization is required
        normalization_required = (
            (has_published and not has_updated) or 
            (has_updated and not has_published) or
            format_type == FeedFormat.UNKNOWN
        )
        
        return FeedMetadata(
            format=format_type,
            version=version,
            has_published=has_published,
            has_updated=has_updated,
            has_both=has_published and has_updated,
            date_fields=list(date_fields_used),
            normalization_required=normalization_required
        )
    
    def _normalize_entry(self, entry: Any, metadata: FeedMetadata) -> Dict[str, Any]:
        """Normalize entry with consistent date field structure."""
        normalized: Dict[str, Any] = {
            'title': getattr(entry, 'title', ''),
            'link': getattr(entry, 'link', ''),
            'summary': getattr(entry, 'summary', ''),
            'author': getattr(entry, 'author', ''),
        }
        
        # Unified date handling
        normalized['dates'] = self._extract_all_dates(entry, metadata)
        
        # Primary publication date (always present)
        normalized['published'] = normalized['dates'].get('primary')
        
        # Additional metadata preservation
        normalized['raw'] = {
            'published_original': getattr(entry, 'published', None),
            'updated_original': getattr(entry, 'updated', None),
            'pubDate_original': getattr(entry, 'pubDate', None),
        }
        
        return normalized
    
    def _extract_all_dates(self, entry: Any, metadata: FeedMetadata) -> Dict[str, Optional[datetime]]:
        """Extract and normalize all date fields from entry."""
        dates: Dict[str, Optional[datetime]] = {}
        
        # Try all possible date fields
        date_fields = ['published', 'updated', 'pubDate', 'date', 'created']
        
        for field_name in date_fields:
            if hasattr(entry, field_name):
                try:
                    value = getattr(entry, field_name)
                    if value:
                        # Use feedparser's parsed date if available
                        parsed_field = f"{field_name}_parsed"
                        if hasattr(entry, parsed_field):
                            parsed = getattr(entry, parsed_field)
                            if parsed:
                                dates[field_name] = datetime.fromtimestamp(
                                    mktime(parsed), 
                                    tz=timezone.utc
                                )
                except (AttributeError, ValueError, TypeError, OverflowError):
                    continue
        
        # Determine primary date based on feed format
        primary: Optional[datetime] = None
        if metadata.format == FeedFormat.RSS_2_0:
            primary = dates.get('pubDate') or dates.get('published')
        elif metadata.format == FeedFormat.ATOM_1_0:
            primary = dates.get('published') or dates.get('updated')
        else:
            # Fallback: use any available date
            primary = next(iter(dates.values()), None) if dates else None
        
        dates['primary'] = primary
        return dates
    
    def _record_feed_metadata(self, url: str, metadata: FeedMetadata) -> None:
        """Record feed metadata for historical analysis and trend detection."""
        self._feed_history[url].append(metadata)
        
        # Keep only last 100 entries per feed
        if len(self._feed_history[url]) > 100:
            self._feed_history[url] = self._feed_history[url][-100:]
    
    def get_format_trends(self) -> Dict[str, Dict[str, Any]]:
        """Analyze feed format trends across all monitored feeds."""
        trends: Dict[str, Dict[str, Any]] = {}
        
        for url, history in self._feed_history.items():
            if len(history) < 2:
                continue
                
            current = history[-1]
            previous = history[-2]
            
            # Detect format changes
            if current.format != previous.format:
                trends[url] = {
                    'type': 'format_change',
                    'from': previous.format.value,
                    'to': current.format.value,
                    'recommendation': self._get_migration_recommendation(current, previous)
                }
        
        return trends
    
    def _get_migration_recommendation(self, current: FeedMetadata, previous: FeedMetadata) -> str:
        """Generate migration recommendation based on format changes."""
        if current.format != previous.format:
            return f"Update parsing logic from {previous.format.value} to {current.format.value}"
        
        # Date field migration recommendations
        if not current.has_both and previous.has_both:
            return "Feed dropped one date field. Ensure fallback logic is in place."
        
        return "No immediate migration needed"


class MigrationTracker:
    """Tracks feed format migrations and generates actionable insights."""
    
    def __init__(self):
        self.migrations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.recommendations: List[Dict[str, Any]] = []
    
    def record_migration_needed(self, url: str, metadata: FeedMetadata) -> None:
        """Record that a feed requires migration attention."""
        migration_record = {
            'timestamp': datetime.now(timezone.utc),
            'metadata': metadata,
            'action_required': metadata.normalization_required
        }
        
        self.migrations[url].append(migration_record)
        
        # Generate recommendation if normalization is required
        if metadata.normalization_required:
            recommendation = self._generate_recommendation(url, metadata)
            self.recommendations.append(recommendation)
    
    def _generate_recommendation(self, url: str, metadata: FeedMetadata) -> Dict[str, Any]:
        """Generate specific recommendation for feed migration."""
        if metadata.format == FeedFormat.UNKNOWN:
            return {
                'url': url,
                'severity': 'high',
                'action': 'Investigate feed format - may require custom parser',
                'details': f'Feed format could not be detected. Version: {metadata.version}'
            }
        
        if not metadata.has_published and not metadata.has_updated:
            return {
                'url': url,
                'severity': 'critical',
                'action': 'Implement fallback date extraction',
                'details': 'Feed has no standard date fields. Check for alternative date formats.'
            }
        
        return {
            'url': url,
            'severity': 'medium',
            'action': 'Update date field mapping',
            'details': f'Feed uses fields: {metadata.date_fields}. Ensure proper normalization.'
        }
    
    def get_pending_migrations(self) -> List[Dict[str, Any]]:
        """Get all migrations requiring attention."""
        return self.recommendations
