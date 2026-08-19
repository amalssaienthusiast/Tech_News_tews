"""
Fetch Policy Configuration for Acquisition Workers.
Location: src/network/fetch_policy.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    """
    Standardized networking and politeness policy for all Zombie and Crawler scrapers.
    """
    user_agent: str = "TechNewsScrapper/7.0 (Polite Intelligence Acquisition; +https://github.com/amalssaienthusiast/Tech_News_Scrapper)"
    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    total_timeout: float = 15.0
    max_redirects: int = 5
    max_raw_bytes: int = 10 * 1024 * 1024         # 10 MB
    max_decompressed_bytes: int = 10 * 1024 * 1024   # 10 MB
    requests_per_second_per_host: float = 2.0
    respect_robots_txt: bool = True
    honor_retry_after: bool = True
    max_retries: int = 3
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    default_headers: Dict[str, str] = field(
        default_factory=lambda: {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        }
    )

    def with_conditional_headers(
        self,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> Dict[str, str]:
        """Generate request headers with conditional validation tokens."""
        headers = dict(self.default_headers)
        headers["User-Agent"] = self.user_agent
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        return headers
