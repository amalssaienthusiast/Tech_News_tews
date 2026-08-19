"""
Functional proxy generator with free proxy discovery, validation, and rotation.

This module provides proxy discovery and management:
- Fetches proxies from multiple free public APIs
- Validates proxy health before use
- Automatic rotation and failover
- Integration with ProxyManager for seamless usage

Free proxy sources:
- Free Proxy List
- ProxyScrape
- GeoNode
- PubProxy
- SpyMe Proxy

Note: Free proxies are typically slow and unreliable. For production use,
consider integrating a paid proxy service like BrightData, Oxylabs, or ScraperAPI.
"""

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp
from bs4 import BeautifulSoup

from src.bypass.proxy_manager import ProxyManager, ProxyProtocol
from src.bypass.stealth import get_stealth_headers

logger = logging.getLogger(__name__)


# =============================================================================
# PROXY SOURCE CONFIGURATION
# =============================================================================

PROXY_APIS: List[Dict[str, Any]] = [
    {
        "name": "proxyscrape_http",
        "url": "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
        "format": "text",
        "protocol": "http",
    },
    {
        "name": "proxyscrape_socks5",
        "url": "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=10000&country=all",
        "format": "text",
        "protocol": "socks5",
    },
    {
        "name": "geonode",
        "url": "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc",
        "format": "json",
        "protocol": "mixed",
    },
    {
        "name": "pubproxy",
        "url": "http://pubproxy.com/api/proxy?limit=10&format=json&type=http",
        "format": "json_pubproxy",
        "protocol": "http",
    },
    {
        "name": "spyme_http",
        "url": "https://spys.me/proxy.txt",
        "format": "spyme",
        "protocol": "http",
    },
    {
        "name": "free_proxy_list",
        "url": "https://free-proxy-list.net/",
        "format": "html_table",
        "protocol": "mixed",
    },
]


@dataclass
class DiscoveredProxy:
    """Information about a discovered proxy."""
    ip: str
    port: int
    protocol: str = "http"
    country: str = ""
    anonymity: str = ""
    source: str = ""
    last_checked: float = 0.0
    response_time_ms: float = 0.0
    is_valid: bool = False
    
    @property
    def url(self) -> str:
        """Get proxy URL."""
        return f"{self.protocol}://{self.ip}:{self.port}"


class ProxyEngine:
    """
    Discovers, validates, and provides working proxies.
    
    Fetches proxies from multiple free public APIs, validates them,
    and provides a pool of working proxies for use in web scraping.
    
    Attributes:
        max_proxies: Maximum proxies to keep in pool.
        validation_timeout: Timeout for proxy validation in seconds.
        refresh_interval: Seconds between automatic refreshes.
        proxy_manager: ProxyManager instance for integration.
    
    Example:
        engine = ProxyEngine()
        await engine.initialize()
        
        # Get a random working proxy
        proxy = await engine.get_random_working_proxy()
        
        # Or refresh the pool
        count = await engine.refresh_pool()
        print(f"Got {count} working proxies")
    """
    
    def __init__(
        self,
        max_proxies: int = 50,
        validation_timeout: float = 10.0,
        refresh_interval: int = 600,
        max_concurrent_validations: int = 20,
    ):
        """
        Initialize proxy engine.
        
        Args:
            max_proxies: Maximum proxies to keep.
            validation_timeout: Validation timeout in seconds.
            refresh_interval: Auto-refresh interval in seconds.
            max_concurrent_validations: Max concurrent validation requests.
        """
        self.max_proxies = max_proxies
        self.validation_timeout = validation_timeout
        self.refresh_interval = refresh_interval
        self.max_concurrent_validations = max_concurrent_validations
        
        self._discovered_proxies: List[DiscoveredProxy] = []
        self._valid_proxies: List[DiscoveredProxy] = []
        self._failed_ips: Set[str] = set()
        self._last_refresh: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None
        self._proxy_manager: Optional[ProxyManager] = None
        self._initialized: bool = False
    
    async def initialize(self) -> None:
        """Initialize the proxy engine and discover proxies."""
        if self._initialized:
            return
        
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.validation_timeout),
            headers=get_stealth_headers(),
        )
        
        self._proxy_manager = ProxyManager(
            rotation_interval=5,
            health_check_interval=300,
            max_failures=3,
        )
        
        # Initial discovery
        await self.refresh_pool()
        self._initialized = True
        
        logger.info(f"ProxyEngine initialized with {len(self._valid_proxies)} valid proxies")
    
    async def close(self) -> None:
        """Close the proxy engine."""
        if self._session:
            await self._session.close()
            self._session = None
        self._initialized = False
    
    async def discover_proxies(self, limit: int = 100) -> List[DiscoveredProxy]:
        """
        Fetch fresh proxies from public APIs.
        
        Args:
            limit: Maximum proxies to discover.
        
        Returns:
            List of discovered proxies (not yet validated).
        """
        if not self._session:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers=get_stealth_headers(),
            )
        
        all_proxies: List[DiscoveredProxy] = []
        
        # Fetch from each source
        tasks = [
            self._fetch_from_source(source)
            for source in PROXY_APIS
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for proxies in results:
            if isinstance(proxies, list):
                all_proxies.extend(proxies)
        
        # Deduplicate by IP:Port
        seen = set()
        unique_proxies = []
        for proxy in all_proxies:
            key = f"{proxy.ip}:{proxy.port}"
            if key not in seen and proxy.ip not in self._failed_ips:
                seen.add(key)
                unique_proxies.append(proxy)
        
        # Shuffle and limit
        random.shuffle(unique_proxies)
        unique_proxies = unique_proxies[:limit]
        
        logger.info(f"Discovered {len(unique_proxies)} unique proxies from {len(PROXY_APIS)} sources")
        return unique_proxies
    
    async def _fetch_from_source(self, source: Dict[str, Any]) -> List[DiscoveredProxy]:
        """Fetch proxies from a single source."""
        proxies = []
        
        try:
            async with self._session.get(source["url"]) as response:
                if response.status != 200:
                    logger.debug(f"Source {source['name']} returned {response.status}")
                    return proxies
                
                if source["format"] == "text":
                    text = await response.text()
                    proxies = self._parse_text_format(text, source)
                    
                elif source["format"] == "json":
                    data = await response.json()
                    proxies = self._parse_json_format(data, source)
                    
                elif source["format"] == "json_pubproxy":
                    data = await response.json()
                    proxies = self._parse_pubproxy_format(data, source)
                    
                elif source["format"] == "spyme":
                    text = await response.text()
                    proxies = self._parse_spyme_format(text, source)
                    
                elif source["format"] == "html_table":
                    html = await response.text()
                    proxies = self._parse_html_table(html, source)
                
                logger.debug(f"Source {source['name']}: found {len(proxies)} proxies")
                
        except Exception as e:
            logger.debug(f"Failed to fetch from {source['name']}: {e}")
        
        return proxies
    
    def _parse_text_format(self, text: str, source: Dict[str, Any]) -> List[DiscoveredProxy]:
        """Parse text format (IP:PORT per line)."""
        proxies = []
        lines = text.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if ":" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    try:
                        ip = parts[0].strip()
                        port = int(parts[1].strip())
                        if self._is_valid_ip(ip) and 1 <= port <= 65535:
                            proxies.append(DiscoveredProxy(
                                ip=ip,
                                port=port,
                                protocol=source.get("protocol", "http"),
                                source=source["name"],
                            ))
                    except ValueError:
                        continue
        
        return proxies
    
    def _parse_json_format(self, data: Dict, source: Dict[str, Any]) -> List[DiscoveredProxy]:
        """Parse GeoNode JSON format."""
        proxies = []
        
        items = data.get("data", [])
        for item in items:
            try:
                ip = item.get("ip", "")
                port = int(item.get("port", 0))
                
                if self._is_valid_ip(ip) and 1 <= port <= 65535:
                    protocol = "socks5" if "socks" in str(item.get("protocols", [])).lower() else "http"
                    
                    proxies.append(DiscoveredProxy(
                        ip=ip,
                        port=port,
                        protocol=protocol,
                        country=item.get("country", ""),
                        anonymity=item.get("anonymityLevel", ""),
                        source=source["name"],
                    ))
            except (ValueError, KeyError):
                continue
        
        return proxies
    
    def _parse_pubproxy_format(self, data: Dict, source: Dict[str, Any]) -> List[DiscoveredProxy]:
        """Parse PubProxy JSON format."""
        proxies = []
        
        items = data.get("data", [])
        for item in items:
            try:
                ip = item.get("ip", "")
                port = int(item.get("port", 0))
                
                if self._is_valid_ip(ip) and 1 <= port <= 65535:
                    proxies.append(DiscoveredProxy(
                        ip=ip,
                        port=port,
                        protocol=item.get("type", "http").lower(),
                        country=item.get("country", ""),
                        source=source["name"],
                    ))
            except (ValueError, KeyError):
                continue
        
        return proxies
    
    def _parse_spyme_format(self, text: str, source: Dict[str, Any]) -> List[DiscoveredProxy]:
        """Parse SpyMe proxy format."""
        proxies = []
        
        # SpyMe format: IP:PORT COUNTRYCODE-ANONYMITY-SSL...
        lines = text.strip().split("\n")
        
        for line in lines:
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                parts = line.split()
                if parts:
                    try:
                        ip_port = parts[0].split(":")
                        ip = ip_port[0]
                        port = int(ip_port[1])
                        
                        if self._is_valid_ip(ip) and 1 <= port <= 65535:
                            proxies.append(DiscoveredProxy(
                                ip=ip,
                                port=port,
                                protocol="http",
                                source=source["name"],
                            ))
                    except (ValueError, IndexError):
                        continue
        
        return proxies
    
    def _parse_html_table(self, html: str, source: Dict[str, Any]) -> List[DiscoveredProxy]:
        """Parse HTML table format (free-proxy-list.net style)."""
        proxies = []
        
        try:
            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table", {"id": "proxylisttable"}) or soup.find("table")
            
            if table:
                rows = table.find_all("tr")[1:]  # Skip header
                
                for row in rows[:50]:  # Limit to 50
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        try:
                            ip = cells[0].get_text().strip()
                            port = int(cells[1].get_text().strip())
                            
                            if self._is_valid_ip(ip) and 1 <= port <= 65535:
                                # Check if HTTPS supported (usually column 6)
                                protocol = "http"
                                if len(cells) > 6 and "yes" in cells[6].get_text().lower():
                                    protocol = "http"  # Still use http:// but site supports HTTPS
                                
                                proxies.append(DiscoveredProxy(
                                    ip=ip,
                                    port=port,
                                    protocol=protocol,
                                    country=cells[3].get_text().strip() if len(cells) > 3 else "",
                                    anonymity=cells[4].get_text().strip() if len(cells) > 4 else "",
                                    source=source["name"],
                                ))
                        except (ValueError, IndexError):
                            continue
        except Exception as e:
            logger.debug(f"HTML parsing error: {e}")
        
        return proxies
    
    def _is_valid_ip(self, ip: str) -> bool:
        """Check if IP address is valid."""
        pattern = r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
        return bool(re.match(pattern, ip))
    
    async def validate_proxy(self, proxy: DiscoveredProxy) -> bool:
        """
        Test if a proxy is working.
        
        Args:
            proxy: Proxy to validate.
        
        Returns:
            True if working, False otherwise.
        """
        test_urls = [
            "https://httpbin.org/ip",
            "https://api.ipify.org?format=json",
        ]
        
        test_url = random.choice(test_urls)
        
        try:
            connector = aiohttp.TCPConnector(force_close=True)
            
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.validation_timeout),
            ) as session:
                start = time.time()
                
                async with session.get(
                    test_url,
                    proxy=proxy.url,
                    headers=get_stealth_headers(),
                ) as response:
                    elapsed = (time.time() - start) * 1000
                    
                    if response.status == 200:
                        proxy.is_valid = True
                        proxy.response_time_ms = elapsed
                        proxy.last_checked = time.time()
                        return True
                        
        except Exception as e:
            logger.debug(f"validate_proxy: suppressed {type(e).__name__}: {e}")
        
        proxy.is_valid = False
        self._failed_ips.add(proxy.ip)
        return False
    
    async def validate_proxies(
        self,
        proxies: List[DiscoveredProxy],
        max_valid: Optional[int] = None
    ) -> List[DiscoveredProxy]:
        """
        Test multiple proxies and return working ones.
        
        Args:
            proxies: List of proxies to validate.
            max_valid: Stop after finding this many valid proxies.
        
        Returns:
            List of validated working proxies.
        """
        if not proxies:
            return []
        
        valid_proxies = []
        semaphore = asyncio.Semaphore(self.max_concurrent_validations)
        
        async def validate_with_limit(proxy: DiscoveredProxy) -> Optional[DiscoveredProxy]:
            async with semaphore:
                if max_valid and len(valid_proxies) >= max_valid:
                    return None
                    
                is_valid = await self.validate_proxy(proxy)
                if is_valid:
                    return proxy
                return None
        
        logger.info(f"Validating {len(proxies)} proxies...")
        
        tasks = [validate_with_limit(p) for p in proxies]
        results = await asyncio.gather(*tasks)
        
        valid_proxies = [p for p in results if p is not None]
        
        # Sort by response time
        valid_proxies.sort(key=lambda p: p.response_time_ms)
        
        logger.info(f"Validated {len(valid_proxies)}/{len(proxies)} proxies as working")
        return valid_proxies
    
    async def refresh_pool(self) -> int:
        """
        Refresh the proxy pool with new validated proxies.
        
        Returns:
            Number of valid proxies in pool.
        """
        # Discover new proxies
        discovered = await self.discover_proxies(limit=self.max_proxies * 3)
        
        if not discovered:
            logger.warning("No proxies discovered from any source")
            return len(self._valid_proxies)
        
        # Validate them
        valid = await self.validate_proxies(
            discovered,
            max_valid=self.max_proxies
        )
        
        # Update pool
        self._valid_proxies = valid
        self._last_refresh = time.time()
        
        # Sync with ProxyManager
        if self._proxy_manager:
            self._proxy_manager.clear()
            for proxy in valid:
                self._proxy_manager.add_proxy(proxy.url)
        
        return len(self._valid_proxies)
    
    async def get_random_working_proxy(self) -> Optional[str]:
        """
        Get a random validated proxy URL.
        
        Returns:
            Proxy URL or None if no proxies available.
        """
        # Check if refresh needed
        if time.time() - self._last_refresh > self.refresh_interval:
            await self.refresh_pool()
        
        if not self._valid_proxies:
            # Try to discover some
            await self.refresh_pool()
        
        if self._valid_proxies:
            proxy = random.choice(self._valid_proxies)
            return proxy.url
        
        return None
    
    async def get_best_proxy(self) -> Optional[str]:
        """
        Get the fastest validated proxy URL.
        
        Returns:
            Proxy URL or None if no proxies available.
        """
        if not self._valid_proxies:
            await self.refresh_pool()
        
        if self._valid_proxies:
            # Already sorted by response time
            return self._valid_proxies[0].url
        
        return None
    
    def get_proxy_manager(self) -> Optional[ProxyManager]:
        """
        Get the integrated ProxyManager.
        
        Returns:
            ProxyManager instance with discovered proxies.
        """
        return self._proxy_manager
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get proxy engine statistics.
        
        Returns:
            Dictionary with stats.
        """
        avg_response = 0.0
        if self._valid_proxies:
            avg_response = sum(p.response_time_ms for p in self._valid_proxies) / len(self._valid_proxies)
        
        return {
            "discovered_count": len(self._discovered_proxies),
            "valid_count": len(self._valid_proxies),
            "failed_ips": len(self._failed_ips),
            "last_refresh": self._last_refresh,
            "avg_response_time_ms": avg_response,
            "sources": len(PROXY_APIS),
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def get_fresh_proxy() -> Optional[str]:
    """
    Quick function to get a fresh validated proxy.
    
    Returns:
        Working proxy URL or None.
    """
    engine = ProxyEngine(max_proxies=10, validation_timeout=5.0)
    
    try:
        await engine.initialize()
        return await engine.get_random_working_proxy()
    finally:
        await engine.close()


async def get_proxy_list(count: int = 10) -> List[str]:
    """
    Get a list of validated proxies.
    
    Args:
        count: Number of proxies to return.
    
    Returns:
        List of working proxy URLs.
    """
    engine = ProxyEngine(max_proxies=count, validation_timeout=5.0)
    
    try:
        await engine.initialize()
        return [p.url for p in engine._valid_proxies[:count]]
    finally:
        await engine.close()
