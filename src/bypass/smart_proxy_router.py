"""
Smart Proxy Router - Phase 3: Geo-Aware Proxy Routing
Automatically routes traffic through country-specific proxies based on domain
"""

import logging
from typing import Dict, Optional, List
from urllib.parse import urlparse
import re

logger = logging.getLogger(__name__)


# Country code to TLD mapping
COUNTRY_TLDS = {
    # Major tech hubs
    "US": [".us", ".com"],  # Default for generic TLDs
    "CN": [".cn", ".com.cn"],
    "IN": [".in", ".co.in"],
    "GB": [".uk", ".co.uk"],
    "DE": [".de"],
    "JP": [".jp", ".co.jp"],
    "KR": [".kr", ".co.kr"],
    "IL": [".il", ".co.il"],
    "SG": [".sg", ".com.sg"],
    "AU": [".au", ".com.au"],
    "CA": [".ca"],
    "FR": [".fr"],
    "BR": [".br", ".com.br"],
    "TW": [".tw", ".com.tw"],
    "SE": [".se"],
    "CH": [".ch"],
    "NL": [".nl"],
    "AE": [".ae"],
    "RU": [".ru"],
    # European
    "IT": [".it"],
    "ES": [".es"],
    "PL": [".pl"],
    "TR": [".tr"],
    "CZ": [".cz"],
    "BE": [".be"],
    "AT": [".at"],
    "PT": [".pt"],
    "FI": [".fi"],
    "DK": [".dk"],
    "NO": [".no"],
    "IE": [".ie"],
    "HU": [".hu"],
    "SK": [".sk"],
    "GR": [".gr"],
    "SI": [".si"],
    "LU": [".lu"],
    "BG": [".bg"],
    "HR": [".hr"],
    "LT": [".lt"],
    "LV": [".lv"],
    "EE": [".ee"],
    "MT": [".mt"],
    "CY": [".cy"],
    "RO": [".ro"],
    # Asian
    "ID": [".id"],
    "TH": [".th"],
    "VN": [".vn"],
    "MY": [".my"],
    "PH": [".ph"],
    "HK": [".hk"],
    "NZ": [".nz"],
    "MX": [".mx"],
    "ZA": [".za"],
}


# Reverse mapping: TLD -> Country
TLD_TO_COUNTRY = {}
for country, tlds in COUNTRY_TLDS.items():
    for tld in tlds:
        TLD_TO_COUNTRY[tld] = country


# Country-specific proxy pools
# Format: {country_code: [proxy_url1, proxy_url2, ...]}
DEFAULT_PROXY_POOLS: Dict[str, List[str]] = {
    # These would be populated from environment variables or config
    # Format: "protocol://user:pass@host:port"
}


class SmartProxyRouter:
    """
    Smart proxy router that automatically selects proxies based on target domain.
    
    Features:
    - Auto-detect country from domain TLD
    - Route through country-specific proxy
    - Fallback to general proxy pool
    - Health checking and rotation
    """
    
    def __init__(self, proxy_manager=None):
        """
        Initialize smart proxy router.
        
        Args:
            proxy_manager: Existing ProxyManager instance (optional)
        """
        self.proxy_manager = proxy_manager
        self.country_proxies: Dict[str, List[str]] = {}
        self.domain_overrides: Dict[str, str] = {}  # domain -> proxy_url
        self._load_proxy_pools()
        
        logger.info("🌐 Smart Proxy Router initialized")
        logger.info(f"   Supported countries: {len(COUNTRY_TLDS)}")
        logger.info(f"   Configured proxy pools: {len(self.country_proxies)}")
        
    def _load_proxy_pools(self):
        """Load proxy pools from environment or config"""
        import os
        
        # Load from environment variables
        # Format: PROXY_POOL_DE=http://proxy1:8080,http://proxy2:8080
        for key, value in os.environ.items():
            if key.startswith("PROXY_POOL_"):
                country = key.replace("PROXY_POOL_", "")
                proxies = [p.strip() for p in value.split(",")]
                self.country_proxies[country] = proxies
                logger.info(f"   Loaded {len(proxies)} proxies for {country}")
                
    def detect_country_from_url(self, url: str) -> Optional[str]:
        """
        Detect country from URL domain.
        
        Args:
            url: Target URL
            
        Returns:
            Country code or None if not detected
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
                
            # Check for country TLD
            for tld, country in TLD_TO_COUNTRY.items():
                if domain.endswith(tld):
                    return country
                    
            # Special cases for major sites
            domain_mapping = {
                "reddit.com": "US",
                "twitter.com": "US",
                "x.com": "US",
                "github.com": "US",
                "youtube.com": "US",
                "google.com": "US",
                "news.ycombinator.com": "US",
                "techcrunch.com": "US",
                "theverge.com": "US",
                "wired.com": "US",
                "arstechnica.com": "US",
                "spiegel.de": "DE",
                "lemonde.fr": "FR",
                "elpais.com": "ES",
                "corriere.it": "IT",
                "guardian.co.uk": "GB",
                "bbc.co.uk": "GB",
            }
            
            for site, country in domain_mapping.items():
                if domain.endswith(site):
                    return country
                    
            return None
            
        except Exception as e:
            logger.error(f"Error detecting country from URL: {e}")
            return None
            
    def get_proxy_for_url(self, url: str) -> Optional[str]:
        """
        Get appropriate proxy for URL.
        
        Args:
            url: Target URL
            
        Returns:
            Proxy URL or None if no proxy needed
        """
        # Check for domain override
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain in self.domain_overrides:
            return self.domain_overrides[domain]
            
        # Detect country
        country = self.detect_country_from_url(url)
        
        if country and country in self.country_proxies:
            # Return random proxy from country pool
            import random
            proxy = random.choice(self.country_proxies[country])
            logger.debug(f"🌐 Routing {domain} through {country} proxy")
            return proxy
            
        # Fallback to general proxy manager
        if self.proxy_manager:
            try:
                proxy_info = self.proxy_manager.get_next_proxy()
                return proxy_info.get_connector_url() if proxy_info else None
            except Exception as e:
                logger.error(f"Error getting proxy from manager: {e}")
                
        return None
        
    def add_country_proxy(self, country: str, proxy_url: str):
        """Add proxy for specific country"""
        if country not in self.country_proxies:
            self.country_proxies[country] = []
        self.country_proxies[country].append(proxy_url)
        logger.info(f"🌐 Added proxy for {country}: {proxy_url}")
        
    def add_domain_override(self, domain: str, proxy_url: str):
        """Add proxy override for specific domain"""
        self.domain_overrides[domain.lower()] = proxy_url
        logger.info(f"🌐 Added domain override: {domain} -> {proxy_url}")
        
    async def fetch_with_smart_proxy(self, url: str, **kwargs) -> Optional[str]:
        """
        Fetch URL using smart proxy routing.
        
        Args:
            url: URL to fetch
            **kwargs: Additional arguments for aiohttp
            
        Returns:
            Response content or None on failure
        """
        import aiohttp
        
        proxy = self.get_proxy_for_url(url)
        
        try:
            connector = None
            if proxy:
                from src.utils.http import create_connector
                connector = create_connector()
                
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    url, 
                    proxy=proxy,
                    timeout=aiohttp.ClientTimeout(total=30),
                    **kwargs
                ) as response:
                    if response.status == 200:
                        return await response.text()
                    elif response.status == 403:
                        logger.warning(f"🌐 Geo-block detected for {url}, trying alternate proxy...")
                        # Try without proxy as fallback
                        return await self._fetch_direct(url, **kwargs)
                    else:
                        logger.error(f"HTTP {response.status} for {url}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
            
    async def _fetch_direct(self, url: str, **kwargs) -> Optional[str]:
        """Fetch without proxy (fallback)"""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=30),
                    **kwargs
                ) as response:
                    if response.status == 200:
                        return await response.text()
                    return None
        except Exception as e:
            logger.error(f"Direct fetch failed for {url}: {e}")
            return None
            
    def get_stats(self) -> Dict:
        """Get routing statistics"""
        return {
            "configured_countries": len(self.country_proxies),
            "total_proxies": sum(len(p) for p in self.country_proxies.values()),
            "domain_overrides": len(self.domain_overrides),
            "supported_tlds": len(TLD_TO_COUNTRY),
            "country_pools": {k: len(v) for k, v in self.country_proxies.items()},
        }


# Global singleton
_smart_router: Optional[SmartProxyRouter] = None


def get_smart_proxy_router(proxy_manager=None) -> SmartProxyRouter:
    """Get or create smart proxy router singleton"""
    global _smart_router
    if _smart_router is None:
        _smart_router = SmartProxyRouter(proxy_manager)
    return _smart_router


# Example usage
if __name__ == "__main__":
    async def test():
        router = get_smart_proxy_router()
        
        # Test URL detection
        test_urls = [
            "https://www.spiegel.de/tech/article.html",  # Germany
            "https://www.lemonde.fr/tech/article.html",  # France
            "https://techcrunch.com/article.html",  # US
            "https://www.reddit.com/r/technology",  # US
        ]
        
        print("🌐 Smart Proxy Routing Tests:")
        for url in test_urls:
            country = router.detect_country_from_url(url)
            proxy = router.get_proxy_for_url(url)
            print(f"   {url}")
            print(f"     Detected: {country or 'Unknown'}")
            print(f"     Proxy: {proxy or 'None (direct)'}")
            print()
            
        print("\n📊 Router Stats:")
        for key, value in router.get_stats().items():
            print(f"   {key}: {value}")
    
    import asyncio
    asyncio.run(test())
