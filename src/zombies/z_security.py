"""
Z-SECURITY — Security Feed Zombie Species.

Specialized RSS zombie that hunts on security intelligence feeds
like NVD, CISA, and major vendor security advisories.
"""

import re
from typing import Any, Dict, Optional

from src.domain.enums import SourceTier, ZombieSpecies
from .z_rss import ZRss


class ZSecurity(ZRss):
    """Security feed hunting zombie."""
    
    species = ZombieSpecies.SECURITY
    _cve_pattern = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)

    def _resolve_tier(self) -> SourceTier:
        """Security feeds default to Tier 2 specialist, or Tier 1 if marked curated."""
        if self.source.tier <= 1:
            return SourceTier.TIER_1_PREMIUM
        return SourceTier.TIER_2_SPECIALIST

    def _build_metadata(self, entry: Any) -> Optional[Dict[str, Any]]:
        """Extract CVE IDs and calculate security severity/priority."""
        title = getattr(entry, "title", "") or ""
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        combined = f"{title} {summary}"

        cve_matches = list(set(self._cve_pattern.findall(combined)))
        cve_ids = [cve.upper() for cve in cve_matches]

        is_critical = "critical" in title.lower() or "active exploitation" in summary.lower() or "zero-day" in combined.lower()
        severity = "critical" if is_critical else ("high" if cve_ids else "medium")

        return {
            "security_source": True,
            "cve_ids": cve_ids,
            "severity": severity,
            "is_primary": is_critical or self.source.tier <= 1,
        }
