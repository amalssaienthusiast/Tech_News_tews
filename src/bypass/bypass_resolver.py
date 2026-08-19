"""
BypassResolver - Escalation Ladder Bypass Engine.

Executes a 5-tier escalation ladder for fetching web content:
Tier 0: Plain HTTP (aiohttp)
Tier 1: Browser Impersonation (primp)
Tier 2: Stealth Playwright Browser (browser_engine)
Tier 3: Proxy Rotation + Stealth Browser (smart_proxy_router)
Tier 4: Archive Fallback (wayback / archive.today via paywall)

Checks for challenge/CAPTCHA pages at every tier and remembers the last working tier for fast-path fetching.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Optional, Tuple, List, Dict, Any

import aiohttp

if TYPE_CHECKING:
    from ..engine.source_registry import SourceDescriptor

logger = logging.getLogger(__name__)

# Challenge page patterns
CHALLENGE_PATTERNS = [
    r"just a moment\.\.\.",
    r"enable javascript and cookies to continue",
    r"cf-browser-verification",
    r"cf-challenge-running",
    r"ray id:",
    r"ddos-guard",
    r"incapsula",
    r"perimeterx",
    r"distilnetworks",
    r"g-recaptcha",
    r"hcaptcha",
    r"cf_turnstile",
    r"challenge-form",
    r"access denied",
    r"403 forbidden",
]

CHALLENGE_REGEX = re.compile("|".join(CHALLENGE_PATTERNS), re.IGNORECASE)

def is_challenge_page(html: str) -> bool:
    """Detect if HTML content is a Cloudflare / anti-bot challenge or CAPTCHA page."""
    if not html or len(html.strip()) < 20:
        return True
    return bool(CHALLENGE_REGEX.search(html))


class BypassResolver:
    """
    Escalation ladder bypass resolver.
    """

    TIERS = [
        (0, "plain_http"),
        (1, "primp_impersonate"),
        (2, "stealth_browser"),
        (3, "proxy_rotation"),
        (4, "archive_fallback"),
    ]

    def __init__(self):
        self._browser_engine = None

    async def fetch(self, source: SourceDescriptor, max_budget_seconds: float = 20.0) -> Optional[str]:
        """
        Fetch URL using escalation ladder starting from source.last_working_tier.
        Enforces a hard per-source timeout across all tried tiers.
        """
        try:
            return await asyncio.wait_for(
                self._escalated_fetch(source),
                timeout=max_budget_seconds
            )
        except asyncio.TimeoutError:
            logger.warning(f"BypassResolver budget of {max_budget_seconds}s exceeded for {source.name} ({source.url})")
            return None
        except Exception as e:
            logger.error(f"BypassResolver error for {source.name}: {e}")
            return None

    async def _escalated_fetch(self, source: SourceDescriptor) -> Optional[str]:
        start_tier = max(0, min(source.last_working_tier, len(self.TIERS) - 1))

        # Try starting from last working tier, then fall back to full ladder if needed
        tiers_to_try = [t for t in range(start_tier, len(self.TIERS))]
        if start_tier > 0:
            # If start_tier fails, try lower tiers as backup
            tiers_to_try.extend([t for t in range(0, start_tier)])

        for tier_id in tiers_to_try:
            tier_name = self.TIERS[tier_id][1]
            logger.debug(f"Attempting Tier {tier_id} ({tier_name}) for {source.name}")
            
            try:
                html = await self._attempt_tier(tier_id, source.url)
                if html and not is_challenge_page(html):
                    source.last_working_tier = tier_id
                    logger.info(f"Tier {tier_id} ({tier_name}) succeeded for {source.name}")
                    return html
                else:
                    logger.debug(f"Tier {tier_id} returned invalid or challenge page for {source.name}")
            except Exception as e:
                logger.debug(f"Tier {tier_id} failed for {source.name}: {e}")

        logger.warning(f"All bypass tiers failed for {source.name} ({source.url})")
        return None

    async def _attempt_tier(self, tier_id: int, url: str) -> Optional[str]:
        """Execute specific bypass tier implementation with strict security boundary."""
        # 1. Authoritative Acquisition Boundary Pre-flight Check across all tiers
        from src.security.ssrf_guard import SSRFGuard, SafeHttpClient, SSRFSecurityError
        try:
            SSRFGuard().validate_url(url)
        except SSRFSecurityError as e:
            logger.warning(f"Acquisition security boundary blocked Tier {tier_id} fetch for '{url}': {e}")
            return None

        if tier_id == 0:
            # Tier 0: Plain HTTP via SafeHttpClient (with per-hop SSRF validation & size bounding)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"}
            try:
                client = SafeHttpClient()
                res = await client.fetch(url, headers=headers, timeout=8.0)
                if res.get("status") == 200:
                    return res.get("content")
                return None
            except Exception as e:
                logger.debug(f"Tier 0 plain_http failed: {e}")
                return None

        elif tier_id == 1:
            # Tier 1: primp HTTP client with TLS impersonation
            try:
                import primp
                client = primp.Client(impersonate="chrome_120", follow_redirects=True, timeout=10)
                loop = asyncio.get_running_loop()
                resp = await loop.run_in_executor(None, lambda: client.get(url))
                if resp.status_code == 200:
                    return resp.text
            except Exception as e:
                logger.debug(f"Primp tier failed: {e}")
            return None

        elif tier_id == 2:
            # Tier 2: Stealth Playwright Browser
            try:
                from .browser_engine import StealthBrowser
                browser = StealthBrowser(headless=True)
                await browser.initialize()
                try:
                    return await browser.fetch_with_bypass(url, bypass_type="auto")
                finally:
                    await browser.close()
            except Exception as e:
                logger.debug(f"Stealth browser tier failed: {e}")
            return None

        elif tier_id == 3:
            # Tier 3: Proxy Rotation + Stealth Browser
            try:
                from .smart_proxy_router import SmartProxyRouter
                from .browser_engine import StealthBrowser
                router = SmartProxyRouter()
                proxy = router.get_proxy_for_url(url)
                browser = StealthBrowser(headless=True)
                await browser.initialize()
                try:
                    if proxy:
                        page = await browser.new_page()
                        resp = await page.goto(url, timeout=20000)
                        return await page.content() if resp else None
                    return await browser.fetch_with_bypass(url, bypass_type="cloudflare")
                finally:
                    await browser.close()
            except Exception as e:
                logger.debug(f"Proxy tier failed: {e}")
            return None

        elif tier_id == 4:
            # Tier 4: Archive Fallback
            bypass = None
            try:
                from .paywall import PaywallBypass, PaywallMethod
                bypass = PaywallBypass()
                res = await bypass.bypass_paywall(url, method=PaywallMethod.WAYBACK)
                if res and res.content:
                    return res.content
                res = await bypass.bypass_paywall(url, method=PaywallMethod.ARCHIVE_TODAY)
                if res and res.content:
                    return res.content
            except Exception as e:
                logger.debug(f"Archive tier failed: {e}")
            finally:
                if bypass:
                    try:
                        await bypass.close()
                    except Exception:
                        pass
            return None

        return None
