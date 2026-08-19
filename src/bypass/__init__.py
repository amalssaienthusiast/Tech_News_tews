"""
Bypass module for anti-bot detection and paywall circumvention.

This module provides advanced web scraping capabilities:
- Anti-bot detection bypass (Cloudflare, Imperva, etc.)
- Paywall bypass strategies (cached, archive, DOM manipulation)
- Browser fingerprint evasion (stealth configuration)
- Proxy rotation, discovery, and management
- Googlebot/Bingbot crawler emulation for LLM-style content access
- Archive/cache fallback strategies
- Research metrics tracking for bypass success rates

Example:
    from src.bypass import AntiBotBypass, PaywallBypass, StealthConfig
    
    # Initialize bypass handlers
    anti_bot = AntiBotBypass()
    paywall = PaywallBypass()
    
    # Fetch protected content with multi-strategy fallback
    content, strategy = await anti_bot.smart_fetch_with_fallback("https://protected-site.com")
    
    # Bypass paywall
    article = await paywall.bypass_paywall("https://news-site.com/article")
    
    # Use Googlebot emulation
    config = StealthConfig.for_googlebot()
    
    # Track bypass metrics for research
    from src.bypass import get_metrics, BypassTechnique
    metrics = get_metrics()
    print(metrics.get_success_rates())
"""

from src.bypass.stealth import (
    StealthConfig,
    get_random_user_agent,
    get_stealth_headers,
    get_googlebot_headers,
    get_archive_urls,
    get_random_googlebot_ua,
    get_random_bingbot_ua,
    GOOGLEBOT_USER_AGENTS,
    BINGBOT_USER_AGENTS,
)
from src.bypass.anti_bot import AntiBotBypass, ProtectionType
from src.bypass.paywall import PaywallBypass, PaywallMethod
from src.bypass.proxy_manager import ProxyManager
from src.bypass.browser_engine import StealthBrowser, fetch_with_stealth_browser
from src.bypass.proxy_engine import ProxyEngine, get_fresh_proxy, get_proxy_list
from src.bypass.content_platform_bypass import (
    ContentPlatformBypass,
    ContentPlatform,
    PlatformBypassResult,
    bypass_content_platform,
)
from src.bypass.bypass_metrics import (
    BypassMetrics,
    BypassTechnique,
    MetricsContext,
    get_metrics,
    TechniqueStats,
    BypassAttempt,
)

__all__ = [
    # Stealth configuration
    "StealthConfig",
    "get_random_user_agent",
    "get_stealth_headers",
    "get_googlebot_headers",
    "get_archive_urls",
    "get_random_googlebot_ua",
    "get_random_bingbot_ua",
    "GOOGLEBOT_USER_AGENTS",
    "BINGBOT_USER_AGENTS",
    # Anti-bot bypass
    "AntiBotBypass",
    "ProtectionType",
    # Paywall bypass
    "PaywallBypass",
    "PaywallMethod",
    # Content platform bypass
    "ContentPlatformBypass",
    "ContentPlatform",
    "PlatformBypassResult",
    "bypass_content_platform",
    # Proxy management
    "ProxyManager",
    "ProxyEngine",
    "get_fresh_proxy",
    "get_proxy_list",
    # Browser automation
    "StealthBrowser",
    "fetch_with_stealth_browser",
    # Research metrics
    "BypassMetrics",
    "BypassTechnique",
    "MetricsContext",
    "get_metrics",
    "TechniqueStats",
    "BypassAttempt",
]

