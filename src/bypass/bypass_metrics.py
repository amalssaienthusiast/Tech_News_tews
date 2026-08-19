"""
Bypass Metrics Module - Research Analytics for Paywall Bypass Techniques.

This module provides comprehensive metrics tracking for security research:
- Success/failure rates per technique
- Platform-specific statistics
- Performance timing analytics
- Export capabilities for research analysis

For academic research, bug bounty, and hackathon projects.
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BypassTechnique(Enum):
    """Enumeration of all bypass techniques tracked."""
    
    # DOM Manipulation
    NEURAL_DOM_ERASER = "neural_dom_eraser"
    CSS_SCRUBBING = "css_scrubbing"
    MUTATION_OBSERVER = "mutation_observer"
    SCRIPT_BLOCKING = "script_blocking"
    
    # JavaScript/Client-Side
    JS_DISABLE = "js_disable"
    LOCALSTORAGE_CLEAR = "localstorage_clear"
    COOKIE_MANIPULATION = "cookie_manipulation"
    
    # Identity Spoofing
    GOOGLEBOT_EMULATION = "googlebot_emulation"
    BINGBOT_EMULATION = "bingbot_emulation"
    REFERER_SPOOF = "referer_spoof"
    
    # Archive/Cache
    GOOGLE_CACHE = "google_cache"
    WAYBACK_MACHINE = "wayback_machine"
    ARCHIVE_TODAY = "archive_today"
    
    # Content Extraction
    JSON_LD_EXTRACTION = "json_ld_extraction"
    RSS_FEED_FALLBACK = "rss_feed_fallback"
    META_OG_EXTRACTION = "meta_og_extraction"
    PRE_PAYWALL_TIMING = "pre_paywall_timing"
    
    # HTTP-Level
    TLS_FINGERPRINT_SPOOF = "tls_fingerprint_spoof"
    HTTP2_SETTINGS = "http2_settings"
    PROXY_ROTATION = "proxy_rotation"
    
    # Anti-Bot Bypass
    CLOUDFLARE_BYPASS = "cloudflare_bypass"
    IMPERVA_BYPASS = "imperva_bypass"
    DATADOME_BYPASS = "datadome_bypass"


class ContentPlatform(Enum):
    """Content platforms tracked for platform-specific stats."""
    MEDIUM = "medium"
    SUBSTACK = "substack"
    GHOST = "ghost"
    WORDPRESS = "wordpress"
    NYT = "nyt"
    WSJ = "wsj"
    BLOOMBERG = "bloomberg"
    GENERIC = "generic"
    UNKNOWN = "unknown"


@dataclass
class BypassAttempt:
    """Record of a single bypass attempt."""
    technique: BypassTechnique
    platform: ContentPlatform
    url: str
    success: bool
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
    content_length: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "technique": self.technique.value,
            "platform": self.platform.value,
            "url": self.url,
            "success": self.success,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "content_length": self.content_length,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class TechniqueStats:
    """Statistics for a single technique."""
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0
    total_content_bytes: int = 0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        return (self.successes / self.attempts * 100) if self.attempts > 0 else 0.0
    
    @property
    def avg_duration_ms(self) -> float:
        """Calculate average duration."""
        return self.total_duration_ms / self.attempts if self.attempts > 0 else 0.0


class BypassMetrics:
    """
    Centralized metrics collection for bypass research.
    
    Provides:
    - Real-time tracking of bypass attempts
    - Success/failure rates per technique
    - Platform-specific analytics
    - Export to JSON for research analysis
    
    Example:
        metrics = BypassMetrics()
        
        # Record an attempt
        metrics.record_attempt(
            technique=BypassTechnique.NEURAL_DOM_ERASER,
            platform=ContentPlatform.MEDIUM,
            url="https://medium.com/article",
            success=True,
            duration_ms=2500,
            content_length=50000
        )
        
        # Get statistics
        stats = metrics.get_technique_stats(BypassTechnique.NEURAL_DOM_ERASER)
        print(f"Success rate: {stats.success_rate:.1f}%")
        
        # Export for research
        metrics.export_to_json("bypass_research_data.json")
    """
    
    _instance: Optional["BypassMetrics"] = None
    _lock = Lock()
    
    def __new__(cls) -> "BypassMetrics":
        """Singleton pattern for global metrics collection."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize metrics storage."""
        if getattr(self, '_initialized', False):
            return
        
        self._attempts: List[BypassAttempt] = []
        self._technique_stats: Dict[BypassTechnique, TechniqueStats] = {
            tech: TechniqueStats() for tech in BypassTechnique
        }
        self._platform_stats: Dict[ContentPlatform, TechniqueStats] = {
            plat: TechniqueStats() for plat in ContentPlatform
        }
        self._start_time = datetime.now()
        self._lock = Lock()
        self._initialized = True
        
        logger.info("BypassMetrics initialized for research tracking")
    
    def record_attempt(
        self,
        technique: BypassTechnique,
        platform: Any,  # Accept any ContentPlatform enum or string
        url: str,
        success: bool,
        duration_ms: float = 0.0,
        content_length: int = 0,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> BypassAttempt:
        """
        Record a bypass attempt for research tracking.
        
        Args:
            technique: The bypass technique used.
            platform: The content platform targeted (any ContentPlatform enum or string).
            url: The URL that was bypassed.
            success: Whether the bypass was successful.
            duration_ms: Time taken in milliseconds.
            content_length: Length of content retrieved.
            error: Error message if failed.
            metadata: Additional research metadata.
        
        Returns:
            The recorded BypassAttempt object.
        """
        # Normalize platform to our enum if possible
        if hasattr(platform, 'value'):
            platform_value = platform.value
            # Try to get our local ContentPlatform
            try:
                local_platform = ContentPlatform(platform_value)
            except ValueError:
                local_platform = ContentPlatform.UNKNOWN
        elif isinstance(platform, str):
            try:
                local_platform = ContentPlatform(platform)
            except ValueError:
                local_platform = ContentPlatform.UNKNOWN
        else:
            local_platform = ContentPlatform.UNKNOWN
        
        attempt = BypassAttempt(
            technique=technique,
            platform=local_platform,
            url=url,
            success=success,
            duration_ms=duration_ms,
            content_length=content_length,
            error=error,
            metadata=metadata or {}
        )
        
        with self._lock:
            self._attempts.append(attempt)
            
            # Update technique stats
            tech_stats = self._technique_stats[technique]
            tech_stats.attempts += 1
            if success:
                tech_stats.successes += 1
            else:
                tech_stats.failures += 1
            tech_stats.total_duration_ms += duration_ms
            tech_stats.total_content_bytes += content_length
            
            # Update platform stats (using normalized platform)
            plat_stats = self._platform_stats[local_platform]
            plat_stats.attempts += 1
            if success:
                plat_stats.successes += 1
            else:
                plat_stats.failures += 1
            plat_stats.total_duration_ms += duration_ms
            plat_stats.total_content_bytes += content_length
        
        logger.debug(
            f"Recorded {technique.value} attempt on {local_platform.value}: "
            f"{'✓' if success else '✗'} ({duration_ms:.0f}ms)"
        )
        
        return attempt
        
        return attempt
    
    def get_technique_stats(self, technique: BypassTechnique) -> TechniqueStats:
        """Get statistics for a specific technique."""
        return self._technique_stats[technique]
    
    def get_platform_stats(self, platform: ContentPlatform) -> TechniqueStats:
        """Get statistics for a specific platform."""
        return self._platform_stats[platform]
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics for all techniques and platforms."""
        with self._lock:
            return {
                "session_start": self._start_time.isoformat(),
                "total_attempts": len(self._attempts),
                "techniques": {
                    tech.value: {
                        "attempts": stats.attempts,
                        "successes": stats.successes,
                        "failures": stats.failures,
                        "success_rate": round(stats.success_rate, 2),
                        "avg_duration_ms": round(stats.avg_duration_ms, 2),
                        "total_bytes": stats.total_content_bytes,
                    }
                    for tech, stats in self._technique_stats.items()
                    if stats.attempts > 0
                },
                "platforms": {
                    plat.value: {
                        "attempts": stats.attempts,
                        "successes": stats.successes,
                        "failures": stats.failures,
                        "success_rate": round(stats.success_rate, 2),
                        "avg_duration_ms": round(stats.avg_duration_ms, 2),
                    }
                    for plat, stats in self._platform_stats.items()
                    if stats.attempts > 0
                }
            }
    
    def get_success_rates(self) -> Dict[str, float]:
        """Get success rates for all techniques (for quick research overview)."""
        return {
            tech.value: round(stats.success_rate, 2)
            for tech, stats in self._technique_stats.items()
            if stats.attempts > 0
        }
    
    def get_recent_attempts(self, count: int = 20) -> List[Dict[str, Any]]:
        """Get the most recent bypass attempts."""
        with self._lock:
            recent = self._attempts[-count:] if len(self._attempts) >= count else self._attempts
            return [a.to_dict() for a in reversed(recent)]
    
    def export_to_json(self, filepath: str) -> None:
        """
        Export all metrics to JSON file for research analysis.
        
        Args:
            filepath: Path to save the JSON file.
        """
        data = {
            "export_time": datetime.now().isoformat(),
            "session_start": self._start_time.isoformat(),
            "summary": self.get_all_stats(),
            "attempts": [a.to_dict() for a in self._attempts],
        }
        
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Exported {len(self._attempts)} bypass attempts to {filepath}")
    
    def reset(self) -> None:
        """Reset all metrics (for new research session)."""
        with self._lock:
            self._attempts.clear()
            for stats in self._technique_stats.values():
                stats.attempts = 0
                stats.successes = 0
                stats.failures = 0
                stats.total_duration_ms = 0.0
                stats.total_content_bytes = 0
            for stats in self._platform_stats.values():
                stats.attempts = 0
                stats.successes = 0
                stats.failures = 0
                stats.total_duration_ms = 0.0
                stats.total_content_bytes = 0
            self._start_time = datetime.now()
        
        logger.info("BypassMetrics reset for new research session")


# Global singleton instance
_metrics = None

def get_metrics() -> BypassMetrics:
    """Get the global BypassMetrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = BypassMetrics()
    return _metrics


class MetricsContext:
    """
    Context manager for timing bypass attempts.
    
    Example:
        with MetricsContext(
            technique=BypassTechnique.NEURAL_DOM_ERASER,
            platform=ContentPlatform.MEDIUM,
            url="https://medium.com/article"
        ) as ctx:
            content = await bypass.execute(url)
            ctx.set_success(True, len(content))
    """
    
    def __init__(
        self,
        technique: BypassTechnique,
        platform: ContentPlatform,
        url: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.technique = technique
        self.platform = platform
        self.url = url
        self.metadata = metadata or {}
        self.success = False
        self.content_length = 0
        self.error: Optional[str] = None
        self._start_time: float = 0.0
    
    def __enter__(self) -> "MetricsContext":
        self._start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self._start_time) * 1000
        
        if exc_type is not None:
            self.success = False
            self.error = str(exc_val)
        
        get_metrics().record_attempt(
            technique=self.technique,
            platform=self.platform,
            url=self.url,
            success=self.success,
            duration_ms=duration_ms,
            content_length=self.content_length,
            error=self.error,
            metadata=self.metadata
        )
        
        return False  # Don't suppress exceptions
    
    def set_success(self, success: bool, content_length: int = 0) -> None:
        """Set the outcome of the bypass attempt."""
        self.success = success
        self.content_length = content_length
    
    def set_error(self, error: str) -> None:
        """Set an error message for failed attempts."""
        self.error = error
        self.success = False
