"""
Z-CORP — Corporate Blog Zombie Species.

Specialized RSS zombie that hunts on official engineering and product blogs
from major tech companies (OpenAI, Google, Microsoft, Apple, etc.).

Sources discovered by this zombie are marked as primary/official in metadata.
"""

from typing import Any, Dict, Optional

from src.domain.enums import SourceTier, ZombieSpecies
from .z_rss import ZRss


class ZCorp(ZRss):
    """Corporate blog hunting zombie."""
    
    species = ZombieSpecies.CORPORATE

    def _resolve_tier(self) -> SourceTier:
        """All corporate blog announcements are treated as Tier 1 Premium."""
        return SourceTier.TIER_1_PREMIUM

    def _build_metadata(self, entry: Any) -> Optional[Dict[str, Any]]:
        """Mark corporate blog sources as primary/authoritative."""
        return {"is_primary": True, "corporate_source": True}
