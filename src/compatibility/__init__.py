"""
Core Compatibility Layer for Tech News Scraper.

Provides permanent solutions for:
- Package deprecations and renames (duckduckgo_search → ddgs)
- RSS feed format normalization and warning suppression
- Future-proof import handling
"""

from .rss_adapter import (
    RSSCompatibilityEngine,
    FeedFormat,
    FeedMetadata,
    FeedResult,
    MigrationTracker,
)
from .package_shim import (
    UniversalPackageShim,
    PackageInfo,
    PackageStatus,
    safe_import,
    package_shim,
)

__all__ = [
    # RSS Compatibility
    "RSSCompatibilityEngine",
    "FeedFormat",
    "FeedMetadata",
    "FeedResult",
    "MigrationTracker",
    # Package Compatibility
    "UniversalPackageShim",
    "PackageInfo",
    "PackageStatus",
    "safe_import",
    "package_shim",
]
