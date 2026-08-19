"""
Internet Browser — Unified browsing capability for Zombie Species.

Provides deep web interaction, wrapping the BypassResolver (escalation ladder)
and primp crawler capabilities. Enables zombies to fetch content while evading
WAFs, Cloudflare challenges, and bot detection.
"""

import asyncio
import logging
from typing import Optional

from src.bypass.bypass_resolver import BypassResolver
from src.engine.source_registry import SourceDescriptor

logger = logging.getLogger(__name__)


class InternetBrowser:
    """
    Shared internet browser capability for the Zombie Swarm.
    
    Provides reliable, anti-bot-bypassing HTTP access using the existing
    BypassResolver escalation ladder (aiohttp -> primp -> stealth playwright -> proxies).
    """
    
    def __init__(self):
        self.resolver = BypassResolver()
        
    async def fetch(self, source: SourceDescriptor, max_budget_seconds: float = 20.0) -> Optional[str]:
        """
        Fetch HTML/XML content for a source, automatically bypassing protections.
        Updates the source's last_working_tier.
        """
        try:
            content = await self.resolver.fetch(source, max_budget_seconds=max_budget_seconds)
            return content
        except Exception as e:
            logger.error(f"InternetBrowser failed to fetch {source.url}: {e}")
            return None
            
    async def fetch_url(self, url: str, tier: int = 1, max_budget_seconds: float = 20.0) -> Optional[str]:
        """
        Fetch a specific URL (not tied to a SourceDescriptor) using a specific tier.
        Useful for corroboration checks or deep linking.
        Tier 1 (primp) is the default for general web fetching.
        """
        # Create a temporary source descriptor to use the resolver
        from src.engine.source_registry import SourceType
        temp_source = SourceDescriptor(
            id="temp",
            url=url,
            name="temp",
            type=SourceType.HTML,
            last_working_tier=tier
        )
        return await self.fetch(temp_source, max_budget_seconds)


# Global shared instance for the swarm
browser = InternetBrowser()
