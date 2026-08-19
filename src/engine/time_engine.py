"""
Time Manager & Timezone Engine for Tech News Scraper.

Provides comprehensive time management capabilities:
- Domain → Timezone mapping
- Regional time format display
- User's local time conversion
- Freshness indicators
- Peak hours detection

Author: Tech News Scraper Team
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TIMEZONE DATABASE - Domain to Timezone Mapping
# ═══════════════════════════════════════════════════════════════════════════════

# Top-Level Domain → Default Timezone
TLD_TIMEZONE_MAP: Dict[str, str] = {
    # Americas
    ".us": "America/New_York",
    ".com": "America/New_York",  # Default for .com (most are US-based)
    ".ca": "America/Toronto",
    ".mx": "America/Mexico_City",
    ".br": "America/Sao_Paulo",
    ".ar": "America/Buenos_Aires",
    
    # Europe
    ".uk": "Europe/London",
    ".co.uk": "Europe/London",
    ".de": "Europe/Berlin",
    ".fr": "Europe/Paris",
    ".nl": "Europe/Amsterdam",
    ".be": "Europe/Brussels",
    ".es": "Europe/Madrid",
    ".it": "Europe/Rome",
    ".ch": "Europe/Zurich",
    ".at": "Europe/Vienna",
    ".pl": "Europe/Warsaw",
    ".se": "Europe/Stockholm",
    ".no": "Europe/Oslo",
    ".dk": "Europe/Copenhagen",
    ".fi": "Europe/Helsinki",
    ".ie": "Europe/Dublin",
    ".pt": "Europe/Lisbon",
    ".gr": "Europe/Athens",
    ".ru": "Europe/Moscow",
    ".ua": "Europe/Kiev",
    
    # Asia
    ".cn": "Asia/Shanghai",
    ".jp": "Asia/Tokyo",
    ".kr": "Asia/Seoul",
    ".in": "Asia/Kolkata",
    ".sg": "Asia/Singapore",
    ".hk": "Asia/Hong_Kong",
    ".tw": "Asia/Taipei",
    ".th": "Asia/Bangkok",
    ".vn": "Asia/Ho_Chi_Minh",
    ".my": "Asia/Kuala_Lumpur",
    ".id": "Asia/Jakarta",
    ".ph": "Asia/Manila",
    ".pk": "Asia/Karachi",
    ".bd": "Asia/Dhaka",
    ".ae": "Asia/Dubai",
    ".il": "Asia/Jerusalem",
    ".tr": "Asia/Istanbul",
    ".sa": "Asia/Riyadh",
    
    # Oceania
    ".au": "Australia/Sydney",
    ".nz": "Pacific/Auckland",
    
    # Africa
    ".za": "Africa/Johannesburg",
    ".eg": "Africa/Cairo",
    ".ng": "Africa/Lagos",
    ".ke": "Africa/Nairobi",
    
    # International/Neutral
    ".io": "UTC",
    ".ai": "UTC",
    ".org": "UTC",
    ".net": "UTC",
    ".edu": "America/New_York",
    ".gov": "America/New_York",
}

# Specific Domain → Timezone (overrides TLD defaults)
DOMAIN_TIMEZONE_MAP: Dict[str, str] = {
    # Major US Tech News
    "techcrunch.com": "America/Los_Angeles",
    "theverge.com": "America/New_York",
    "wired.com": "America/Los_Angeles",
    "arstechnica.com": "America/New_York",
    "engadget.com": "America/New_York",
    "cnet.com": "America/Los_Angeles",
    "zdnet.com": "America/New_York",
    "venturebeat.com": "America/Los_Angeles",
    "mashable.com": "America/New_York",
    "gizmodo.com": "America/New_York",
    "tomshardware.com": "America/New_York",
    "macrumors.com": "America/Los_Angeles",
    "9to5mac.com": "America/Los_Angeles",
    "9to5google.com": "America/Los_Angeles",
    "androidauthority.com": "America/Los_Angeles",
    "androidcentral.com": "America/New_York",
    
    # International/Wire Services (UTC)
    "reuters.com": "UTC",
    "apnews.com": "UTC",
    "afp.com": "UTC",
    "bbc.com": "Europe/London",
    "bbc.co.uk": "Europe/London",
    
    # UK Tech
    "theregister.com": "Europe/London",
    "techradar.com": "Europe/London",
    "thenextweb.com": "Europe/Amsterdam",
    
    # Europe Tech
    "heise.de": "Europe/Berlin",
    "golem.de": "Europe/Berlin",
    "lemonde.fr": "Europe/Paris",
    
    # Russia
    "ria.ru": "Europe/Moscow",
    "tass.com": "Europe/Moscow",
    "rt.com": "Europe/Moscow",
    "habr.com": "Europe/Moscow",
    
    # India
    "thehindu.com": "Asia/Kolkata",
    "timesofindia.com": "Asia/Kolkata",
    "ndtv.com": "Asia/Kolkata",
    "indianexpress.com": "Asia/Kolkata",
    "moneycontrol.com": "Asia/Kolkata",
    "livemint.com": "Asia/Kolkata",
    
    # China
    "scmp.com": "Asia/Hong_Kong",
    "chinadaily.com.cn": "Asia/Shanghai",
    "xinhuanet.com": "Asia/Shanghai",
    
    # Japan
    "nhk.or.jp": "Asia/Tokyo",
    "japantimes.co.jp": "Asia/Tokyo",
    "nikkei.com": "Asia/Tokyo",
    
    # Australia
    "abc.net.au": "Australia/Sydney",
    "smh.com.au": "Australia/Sydney",
    "theaustralian.com.au": "Australia/Sydney",
    
    # Singapore
    "straitstimes.com": "Asia/Singapore",
    "channelnewsasia.com": "Asia/Singapore",
    
    # Middle East
    "aljazeera.com": "Asia/Qatar",
    "arabnews.com": "Asia/Riyadh",
}

# Timezone → Display Abbreviation
TIMEZONE_ABBREVIATIONS: Dict[str, str] = {
    "America/New_York": "EST/EDT",
    "America/Los_Angeles": "PST/PDT",
    "America/Chicago": "CST/CDT",
    "America/Denver": "MST/MDT",
    "America/Toronto": "EST/EDT",
    "Europe/London": "GMT/BST",
    "Europe/Paris": "CET/CEST",
    "Europe/Berlin": "CET/CEST",
    "Europe/Moscow": "MSK",
    "Asia/Tokyo": "JST",
    "Asia/Shanghai": "CST",
    "Asia/Kolkata": "IST",
    "Asia/Singapore": "SGT",
    "Asia/Hong_Kong": "HKT",
    "Asia/Seoul": "KST",
    "Australia/Sydney": "AEST/AEDT",
    "Pacific/Auckland": "NZST/NZDT",
    "UTC": "UTC",
}

# Timezone → Country Flag Emoji
TIMEZONE_FLAGS: Dict[str, str] = {
    "America/New_York": "🇺🇸",
    "America/Los_Angeles": "🇺🇸",
    "America/Chicago": "🇺🇸",
    "America/Toronto": "🇨🇦",
    "Europe/London": "🇬🇧",
    "Europe/Paris": "🇫🇷",
    "Europe/Berlin": "🇩🇪",
    "Europe/Moscow": "🇷🇺",
    "Europe/Amsterdam": "🇳🇱",
    "Asia/Tokyo": "🇯🇵",
    "Asia/Shanghai": "🇨🇳",
    "Asia/Kolkata": "🇮🇳",
    "Asia/Singapore": "🇸🇬",
    "Asia/Hong_Kong": "🇭🇰",
    "Asia/Seoul": "🇰🇷",
    "Australia/Sydney": "🇦🇺",
    "Pacific/Auckland": "🇳🇿",
    "UTC": "🌐",
}


# ═══════════════════════════════════════════════════════════════════════════════
# REGIONAL TIME FORMATS
# ═══════════════════════════════════════════════════════════════════════════════

class TimeFormat(Enum):
    """Time format styles for different regions."""
    US = "us"           # Jan 20, 2026, 3:45 PM
    EU_24H = "eu_24h"   # 20 Jan 2026, 15:45
    ISO = "iso"         # 2026-01-20 15:45
    RELATIVE = "relative"  # 2 hours ago


@dataclass
class RegionalFormat:
    """Regional time format configuration."""
    date_format: str
    time_format: str
    use_24h: bool
    locale_code: str
    
    def format_datetime(self, dt: datetime) -> str:
        """Format datetime according to regional preferences."""
        if self.use_24h:
            time_str = dt.strftime("%H:%M")
        else:
            time_str = dt.strftime("%I:%M %p").lstrip("0")
        
        date_str = dt.strftime(self.date_format)
        return f"{date_str}, {time_str}"


# Regional format configurations
REGIONAL_FORMATS: Dict[str, RegionalFormat] = {
    # US Format: Jan 20, 2026, 3:45 PM EST
    "America/New_York": RegionalFormat("%b %d, %Y", "%I:%M %p", False, "en_US"),
    "America/Los_Angeles": RegionalFormat("%b %d, %Y", "%I:%M %p", False, "en_US"),
    "America/Chicago": RegionalFormat("%b %d, %Y", "%I:%M %p", False, "en_US"),
    
    # UK Format: 20 Jan 2026, 15:45 GMT
    "Europe/London": RegionalFormat("%d %b %Y", "%H:%M", True, "en_GB"),
    
    # EU Format: 20 Jan 2026, 15:45 CET
    "Europe/Paris": RegionalFormat("%d %b %Y", "%H:%M", True, "fr_FR"),
    "Europe/Berlin": RegionalFormat("%d. %b %Y", "%H:%M", True, "de_DE"),
    "Europe/Amsterdam": RegionalFormat("%d %b %Y", "%H:%M", True, "nl_NL"),
    
    # Russia: 20 янв. 2026 г., 22:45 MSK
    "Europe/Moscow": RegionalFormat("%d %b %Y", "%H:%M", True, "ru_RU"),
    
    # India: 20 Jan 2026, 15:45 IST
    "Asia/Kolkata": RegionalFormat("%d %b %Y", "%H:%M", True, "en_IN"),
    
    # Japan: 2026年1月20日 22:45 JST (simplified to ISO-like)
    "Asia/Tokyo": RegionalFormat("%Y-%m-%d", "%H:%M", True, "ja_JP"),
    
    # China: 2026-01-20 22:45 CST
    "Asia/Shanghai": RegionalFormat("%Y-%m-%d", "%H:%M", True, "zh_CN"),
    
    # Default (ISO-like)
    "UTC": RegionalFormat("%Y-%m-%d", "%H:%M", True, "en_US"),
}


# ═══════════════════════════════════════════════════════════════════════════════
# FRESHNESS INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════

class FreshnessLevel(Enum):
    """Article freshness levels."""
    BREAKING = "breaking"      # < 15 minutes
    FRESH = "fresh"            # < 1 hour
    RECENT = "recent"          # < 6 hours
    TODAY = "today"            # < 24 hours
    THIS_WEEK = "this_week"    # < 7 days
    OLDER = "older"            # > 7 days


@dataclass
class FreshnessIndicator:
    """Freshness indicator with visual styling."""
    level: FreshnessLevel
    emoji: str
    color: str
    label: str


FRESHNESS_CONFIG = {
    FreshnessLevel.BREAKING: FreshnessIndicator(
        FreshnessLevel.BREAKING, "🔴", "#ff5555", "BREAKING"
    ),
    FreshnessLevel.FRESH: FreshnessIndicator(
        FreshnessLevel.FRESH, "🟢", "#50fa7b", "Fresh"
    ),
    FreshnessLevel.RECENT: FreshnessIndicator(
        FreshnessLevel.RECENT, "🟡", "#f1fa8c", "Recent"
    ),
    FreshnessLevel.TODAY: FreshnessIndicator(
        FreshnessLevel.TODAY, "🔵", "#8be9fd", "Today"
    ),
    FreshnessLevel.THIS_WEEK: FreshnessIndicator(
        FreshnessLevel.THIS_WEEK, "⚪", "#6272a4", "This Week"
    ),
    FreshnessLevel.OLDER: FreshnessIndicator(
        FreshnessLevel.OLDER, "⬜", "#44475a", "Older"
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# TIMEZONE MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class TimeZoneManager:
    """
    Manages timezone detection and mapping for news sources.
    
    Determines the appropriate timezone for a news source based on:
    1. Specific domain mapping (highest priority)
    2. Top-level domain defaults
    3. Fallback to UTC
    """
    
    def __init__(self):
        self._domain_cache: Dict[str, str] = {}
    
    def get_timezone_for_domain(self, domain: str) -> str:
        """
        Get timezone string for a domain.
        
        Args:
            domain: Domain name (e.g., 'techcrunch.com')
        
        Returns:
            Timezone string (e.g., 'America/Los_Angeles')
        """
        # Check cache
        if domain in self._domain_cache:
            return self._domain_cache[domain]
        
        # Clean domain
        domain = domain.lower().strip()
        if domain.startswith("www."):
            domain = domain[4:]
        
        # 1. Check specific domain mapping
        if domain in DOMAIN_TIMEZONE_MAP:
            tz = DOMAIN_TIMEZONE_MAP[domain]
            self._domain_cache[domain] = tz
            return tz
        
        # 2. Check TLD mapping
        for tld, tz in TLD_TIMEZONE_MAP.items():
            if domain.endswith(tld):
                self._domain_cache[domain] = tz
                return tz
        
        # 3. Default to UTC
        self._domain_cache[domain] = "UTC"
        return "UTC"
    
    def get_timezone_for_url(self, url: str) -> str:
        """Get timezone for a URL."""
        try:
            domain = urlparse(url).netloc
            return self.get_timezone_for_domain(domain)
        except Exception:
            return "UTC"
    
    def get_zoneinfo(self, tz_str: str) -> ZoneInfo:
        """Get ZoneInfo object for timezone string."""
        try:
            return ZoneInfo(tz_str)
        except Exception:
            return ZoneInfo("UTC")
    
    def get_abbreviation(self, tz_str: str) -> str:
        """Get timezone abbreviation (e.g., 'EST', 'MSK')."""
        return TIMEZONE_ABBREVIATIONS.get(tz_str, tz_str.split("/")[-1])
    
    def get_flag(self, tz_str: str) -> str:
        """Get country flag emoji for timezone."""
        return TIMEZONE_FLAGS.get(tz_str, "🌐")


# ═══════════════════════════════════════════════════════════════════════════════
# TIME FORMAT MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class TimeFormatManager:
    """
    Manages regional time formatting.
    
    Formats times according to regional conventions:
    - US: 12-hour with AM/PM
    - Europe: 24-hour
    - Asia: 24-hour with locale-specific date formats
    """
    
    def __init__(self, tz_manager: TimeZoneManager):
        self._tz_manager = tz_manager
    
    def get_regional_format(self, tz_str: str) -> RegionalFormat:
        """Get regional format for timezone."""
        return REGIONAL_FORMATS.get(tz_str, REGIONAL_FORMATS["UTC"])
    
    def format_datetime(
        self,
        dt: datetime,
        source_tz: str,
        include_timezone: bool = True,
        include_flag: bool = True,
    ) -> str:
        """
        Format datetime in regional style.
        
        Args:
            dt: Datetime to format (should be timezone-aware or UTC)
            source_tz: Source timezone string
            include_timezone: Whether to include timezone abbreviation
            include_flag: Whether to include country flag
        
        Returns:
            Formatted time string (e.g., "🇺🇸 Jan 20, 2026, 3:45 PM EST")
        """
        try:
            # Convert to source timezone
            tz = self._tz_manager.get_zoneinfo(source_tz)
            
            # Ensure datetime is timezone-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            local_dt = dt.astimezone(tz)
            
            # Get regional format
            regional = self.get_regional_format(source_tz)
            formatted = regional.format_datetime(local_dt)
            
            # Add timezone abbreviation
            if include_timezone:
                abbrev = self._tz_manager.get_abbreviation(source_tz)
                formatted = f"{formatted} {abbrev}"
            
            # Add flag
            if include_flag:
                flag = self._tz_manager.get_flag(source_tz)
                formatted = f"{flag} {formatted}"
            
            return formatted
            
        except Exception as e:
            logger.debug(f"Time format error: {e}")
            return dt.strftime("%Y-%m-%d %H:%M UTC")
    
    def format_relative(self, dt: datetime) -> str:
        """
        Format datetime as relative time (e.g., "2 hours ago").
        
        Args:
            dt: Datetime to format
        
        Returns:
            Relative time string
        """
        now = datetime.now(timezone.utc)
        
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        diff = now - dt
        
        if diff < timedelta(minutes=1):
            return "Just now"
        elif diff < timedelta(hours=1):
            mins = int(diff.total_seconds() / 60)
            return f"{mins} min{'s' if mins != 1 else ''} ago"
        elif diff < timedelta(hours=24):
            hours = int(diff.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif diff < timedelta(days=7):
            days = diff.days
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif diff < timedelta(days=30):
            weeks = diff.days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        else:
            months = diff.days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"


# ═══════════════════════════════════════════════════════════════════════════════
# FRESHNESS CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

class FreshnessCalculator:
    """Calculates article freshness based on publication time."""
    
    @staticmethod
    def get_freshness(published_at: Optional[datetime]) -> FreshnessIndicator:
        """
        Calculate freshness indicator for an article.
        
        Args:
            published_at: Article publication datetime
        
        Returns:
            FreshnessIndicator with level, emoji, color, and label
        """
        if published_at is None:
            return FRESHNESS_CONFIG[FreshnessLevel.OLDER]
        
        now = datetime.now(timezone.utc)
        
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        
        age = now - published_at
        
        if age < timedelta(minutes=15):
            return FRESHNESS_CONFIG[FreshnessLevel.BREAKING]
        elif age < timedelta(hours=1):
            return FRESHNESS_CONFIG[FreshnessLevel.FRESH]
        elif age < timedelta(hours=6):
            return FRESHNESS_CONFIG[FreshnessLevel.RECENT]
        elif age < timedelta(hours=24):
            return FRESHNESS_CONFIG[FreshnessLevel.TODAY]
        elif age < timedelta(days=7):
            return FRESHNESS_CONFIG[FreshnessLevel.THIS_WEEK]
        else:
            return FRESHNESS_CONFIG[FreshnessLevel.OLDER]
    
    @staticmethod
    def get_age_string(published_at: Optional[datetime]) -> str:
        """Get human-readable age string."""
        if published_at is None:
            return "Unknown"
        
        now = datetime.now(timezone.utc)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        
        age = now - published_at
        
        if age.total_seconds() < 0:
            return "Scheduled"
        elif age < timedelta(minutes=1):
            return "Just now"
        elif age < timedelta(hours=1):
            mins = int(age.total_seconds() / 60)
            return f"{mins}m ago"
        elif age < timedelta(hours=24):
            hours = int(age.total_seconds() / 3600)
            return f"{hours}h ago"
        elif age < timedelta(days=7):
            days = age.days
            return f"{days}d ago"
        else:
            return published_at.strftime("%b %d")


# ═══════════════════════════════════════════════════════════════════════════════
# TIME ENGINE - MAIN FACADE
# ═══════════════════════════════════════════════════════════════════════════════

class TimeEngine:
    """
    Main time management engine for the news scraper.
    
    Provides a unified interface for all time-related operations:
    - Timezone detection for sources
    - Regional time formatting
    - Local time conversion
    - Freshness indicators
    
    Example:
        engine = TimeEngine()
        
        # Get timezone for a source
        tz = engine.get_source_timezone("https://techcrunch.com/article")
        # Returns: "America/Los_Angeles"
        
        # Format article time
        formatted = engine.format_article_time(article)
        # Returns: "🇺🇸 Jan 20, 2026, 3:45 PM PST"
        
        # Get freshness indicator
        freshness = engine.get_freshness(article.published_at)
        # Returns: FreshnessIndicator with emoji, color, label
    """
    
    def __init__(self, user_timezone: Optional[str] = None):
        """
        Initialize TimeEngine.
        
        Args:
            user_timezone: User's timezone for local conversion (auto-detected if None)
        """
        self._tz_manager = TimeZoneManager()
        self._format_manager = TimeFormatManager(self._tz_manager)
        self._freshness_calc = FreshnessCalculator()
        
        # Auto-detect or use provided user timezone
        if user_timezone:
            self._user_tz = user_timezone
        else:
            self._user_tz = self._detect_user_timezone()
        
        logger.debug(f"TimeEngine initialized with user timezone: {self._user_tz}")
    
    def _detect_user_timezone(self) -> str:
        """Detect user's system timezone."""
        try:
            import time
            # Get local timezone offset
            if time.daylight:
                offset = -time.altzone
            else:
                offset = -time.timezone
            
            # Try to get named timezone
            try:
                from datetime import timezone as tz_module
                local = datetime.now().astimezone()
                return str(local.tzinfo)
            except Exception as e:
                logger.debug(f"_detect_user_timezone: suppressed {type(e).__name__}: {e}")
            
            # Fallback to offset-based
            hours = offset // 3600
            if hours >= 0:
                return f"Etc/GMT-{hours}"
            else:
                return f"Etc/GMT+{-hours}"
                
        except Exception:
            return "UTC"
    
    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────
    
    def get_source_timezone(self, url_or_domain: str) -> str:
        """
        Get timezone for a news source.
        
        Args:
            url_or_domain: Full URL or domain name
        
        Returns:
            Timezone string (e.g., 'America/Los_Angeles')
        """
        if "://" in url_or_domain:
            return self._tz_manager.get_timezone_for_url(url_or_domain)
        return self._tz_manager.get_timezone_for_domain(url_or_domain)
    
    def format_article_time(
        self,
        published_at: Optional[datetime],
        source_url: Optional[str] = None,
        source_tz: Optional[str] = None,
        style: str = "full",
    ) -> str:
        """
        Format article publication time.
        
        Args:
            published_at: Article publication datetime
            source_url: Source URL for timezone detection
            source_tz: Explicit source timezone (overrides URL detection)
            style: Format style - "full", "compact", "relative"
        
        Returns:
            Formatted time string
        """
        if published_at is None:
            return "Unknown"
        
        # Determine source timezone
        if source_tz is None and source_url:
            source_tz = self.get_source_timezone(source_url)
        elif source_tz is None:
            source_tz = "UTC"
        
        if style == "relative":
            return self._format_manager.format_relative(published_at)
        elif style == "compact":
            return self._freshness_calc.get_age_string(published_at)
        else:  # full
            return self._format_manager.format_datetime(
                published_at, 
                source_tz,
                include_timezone=True,
                include_flag=True,
            )
    
    def format_with_local(
        self,
        published_at: Optional[datetime],
        source_url: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Format time with both source and local time.
        
        Args:
            published_at: Article publication datetime
            source_url: Source URL for timezone detection
        
        Returns:
            Tuple of (source_time_str, local_time_str)
        """
        if published_at is None:
            return ("Unknown", "Unknown")
        
        source_tz = self.get_source_timezone(source_url) if source_url else "UTC"
        
        # Format source time
        source_str = self._format_manager.format_datetime(
            published_at, source_tz, include_timezone=True, include_flag=True
        )
        
        # Format local time
        local_str = self._format_manager.format_datetime(
            published_at, self._user_tz, include_timezone=True, include_flag=True
        )
        
        return (source_str, local_str)
    
    def get_freshness(self, published_at: Optional[datetime]) -> FreshnessIndicator:
        """
        Get freshness indicator for article.
        
        Args:
            published_at: Article publication datetime
        
        Returns:
            FreshnessIndicator with emoji, color, and label
        """
        return self._freshness_calc.get_freshness(published_at)
    
    def get_timezone_info(self, url_or_domain: str) -> Dict[str, str]:
        """
        Get full timezone info for a source.
        
        Args:
            url_or_domain: URL or domain
        
        Returns:
            Dict with timezone, abbreviation, flag, and region
        """
        tz = self.get_source_timezone(url_or_domain)
        return {
            "timezone": tz,
            "abbreviation": self._tz_manager.get_abbreviation(tz),
            "flag": self._tz_manager.get_flag(tz),
            "region": tz.split("/")[0] if "/" in tz else "Unknown",
        }
    
    def convert_to_local(self, dt: datetime, from_tz: str) -> datetime:
        """
        Convert datetime to user's local timezone.
        
        Args:
            dt: Datetime to convert
            from_tz: Source timezone string
        
        Returns:
            Datetime in user's local timezone
        """
        if dt.tzinfo is None:
            source_tz = self._tz_manager.get_zoneinfo(from_tz)
            dt = dt.replace(tzinfo=source_tz)
        
        user_tz = self._tz_manager.get_zoneinfo(self._user_tz)
        return dt.astimezone(user_tz)
    
    def convert_to_utc(self, dt: datetime, from_tz: str) -> datetime:
        """
        Convert datetime to UTC.
        
        Args:
            dt: Datetime to convert
            from_tz: Source timezone string
        
        Returns:
            Datetime in UTC
        """
        if dt.tzinfo is None:
            source_tz = self._tz_manager.get_zoneinfo(from_tz)
            dt = dt.replace(tzinfo=source_tz)
        
        return dt.astimezone(timezone.utc)
    
    @property
    def user_timezone(self) -> str:
        """Get user's timezone string."""
        return self._user_tz
    
    @user_timezone.setter
    def user_timezone(self, tz: str):
        """Set user's timezone."""
        self._user_tz = tz


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

# Global time engine instance
_time_engine: Optional[TimeEngine] = None


def get_time_engine() -> TimeEngine:
    """Get the global TimeEngine instance."""
    global _time_engine
    if _time_engine is None:
        _time_engine = TimeEngine()
    return _time_engine


def reset_time_engine():
    """Reset the global TimeEngine instance."""
    global _time_engine
    _time_engine = None


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def format_article_time(
    published_at: Optional[datetime],
    source_url: Optional[str] = None,
    style: str = "full",
) -> str:
    """Convenience function to format article time."""
    return get_time_engine().format_article_time(published_at, source_url, style=style)


def get_freshness(published_at: Optional[datetime]) -> FreshnessIndicator:
    """Convenience function to get freshness indicator."""
    return get_time_engine().get_freshness(published_at)


def get_source_timezone(url_or_domain: str) -> str:
    """Convenience function to get source timezone."""
    return get_time_engine().get_source_timezone(url_or_domain)
