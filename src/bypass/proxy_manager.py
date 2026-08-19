"""
Proxy rotation and management module.

This module provides proxy support for web scraping:
- HTTP/HTTPS/SOCKS5 proxy support
- Automatic rotation on failure or interval
- Health checking and validation
- Load balancing across proxy pool

Proxies help avoid IP-based blocking and rate limiting.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


class ProxyProtocol(Enum):
    """Supported proxy protocols."""
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


@dataclass
class ProxyInfo:
    """Information about a proxy server."""
    url: str
    protocol: ProxyProtocol = ProxyProtocol.HTTP
    username: Optional[str] = None
    password: Optional[str] = None
    is_healthy: bool = True
    last_used: float = 0.0
    last_check: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    avg_response_time_ms: float = 0.0
    
    @property
    def failure_rate(self) -> float:
        """Calculate failure rate."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return self.failure_count / total
    
    def get_connector_url(self) -> str:
        """Get URL for aiohttp connector."""
        if self.username and self.password:
            parsed = urlparse(self.url)
            return f"{parsed.scheme}://{self.username}:{self.password}@{parsed.netloc}"
        return self.url


class ProxyManager:
    """
    Proxy rotation and management.
    
    Manages a pool of proxy servers for web scraping, with automatic
    rotation, health checking, and failure handling.
    
    Attributes:
        proxies: List of available proxies.
        rotation_interval: Requests before automatic rotation.
        health_check_interval: Seconds between health checks.
        max_failures: Max failures before marking proxy unhealthy.
    
    Example:
        manager = ProxyManager()
        manager.add_proxy("http://proxy1:8080")
        manager.add_proxy("socks5://proxy2:1080")
        
        proxy = manager.get_next_proxy()
        # Use proxy for request...
        manager.mark_success(proxy)
    """
    
    def __init__(
        self,
        rotation_interval: int = 10,
        health_check_interval: int = 300,
        max_failures: int = 3
    ):
        """
        Initialize proxy manager.
        
        Args:
            rotation_interval: Requests before rotation.
            health_check_interval: Seconds between health checks.
            max_failures: Max failures before unhealthy.
        """
        self.proxies: List[ProxyInfo] = []
        self.rotation_interval = rotation_interval
        self.health_check_interval = health_check_interval
        self.max_failures = max_failures
        
        self._current_index = 0
        self._request_count = 0
        self._failed_proxies: Set[str] = set()
    
    def add_proxy(
        self,
        url: str,
        username: Optional[str] = None,
        password: Optional[str] = None
    ) -> None:
        """
        Add a proxy to the pool.
        
        Args:
            url: Proxy URL (e.g., "http://proxy:8080").
            username: Optional proxy username.
            password: Optional proxy password.
        """
        # Parse protocol
        parsed = urlparse(url)
        protocol = ProxyProtocol.HTTP
        
        if parsed.scheme == "https":
            protocol = ProxyProtocol.HTTPS
        elif parsed.scheme in ["socks5", "socks"]:
            protocol = ProxyProtocol.SOCKS5
        
        # Extract auth from URL if present
        if parsed.username and not username:
            username = parsed.username
        if parsed.password and not password:
            password = parsed.password
        
        # Rebuild clean URL
        clean_url = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            clean_url += f":{parsed.port}"
        
        proxy = ProxyInfo(
            url=clean_url,
            protocol=protocol,
            username=username,
            password=password,
        )
        
        self.proxies.append(proxy)
        logger.info(f"Added proxy: {clean_url}")
    
    def add_proxies_from_list(self, proxy_list: List[str]) -> None:
        """
        Add multiple proxies from a list.
        
        Args:
            proxy_list: List of proxy URLs.
        """
        for url in proxy_list:
            try:
                self.add_proxy(url)
            except Exception as e:
                logger.warning(f"Failed to add proxy {url}: {e}")
    
    def get_next_proxy(self) -> Optional[str]:
        """
        Get the next available proxy URL.
        
        Rotates through healthy proxies. Returns None if no proxies available.
        
        Returns:
            Proxy URL or None.
        """
        if not self.proxies:
            return None
        
        healthy_proxies = [p for p in self.proxies if p.is_healthy]
        
        if not healthy_proxies:
            # Try to recover failed proxies
            self._recover_failed_proxies()
            healthy_proxies = [p for p in self.proxies if p.is_healthy]
            
            if not healthy_proxies:
                logger.warning("No healthy proxies available")
                return None
        
        # Increment request count and check if rotation needed
        self._request_count += 1
        if self._request_count >= self.rotation_interval:
            self._current_index = (self._current_index + 1) % len(healthy_proxies)
            self._request_count = 0
        
        # Get current proxy
        proxy = healthy_proxies[self._current_index % len(healthy_proxies)]
        proxy.last_used = time.time()
        
        return proxy.get_connector_url()
    
    def get_random_proxy(self) -> Optional[str]:
        """
        Get a random healthy proxy.
        
        Returns:
            Random proxy URL or None.
        """
        healthy = [p for p in self.proxies if p.is_healthy]
        if not healthy:
            return None
        
        proxy = random.choice(healthy)
        proxy.last_used = time.time()
        return proxy.get_connector_url()
    
    def mark_success(self, proxy_url: str) -> None:
        """
        Mark a proxy request as successful.
        
        Args:
            proxy_url: The proxy URL used.
        """
        for proxy in self.proxies:
            if proxy_url.startswith(proxy.url):
                proxy.success_count += 1
                self._failed_proxies.discard(proxy.url)
                break
    
    def mark_failure(self, proxy_url: str) -> None:
        """
        Mark a proxy request as failed.
        
        Args:
            proxy_url: The proxy URL used.
        """
        for proxy in self.proxies:
            if proxy_url.startswith(proxy.url):
                proxy.failure_count += 1
                
                if proxy.failure_count >= self.max_failures:
                    proxy.is_healthy = False
                    self._failed_proxies.add(proxy.url)
                    logger.warning(f"Proxy marked unhealthy: {proxy.url}")
                break
    
    def _recover_failed_proxies(self) -> None:
        """Try to recover previously failed proxies."""
        current_time = time.time()
        
        for proxy in self.proxies:
            if not proxy.is_healthy:
                # Recover if enough time has passed
                if current_time - proxy.last_check > self.health_check_interval:
                    proxy.is_healthy = True
                    proxy.failure_count = 0
                    proxy.last_check = current_time
                    logger.info(f"Attempting to recover proxy: {proxy.url}")
    
    async def check_proxy_health(self, proxy_url: str) -> bool:
        """
        Check if a proxy is working.
        
        Args:
            proxy_url: Proxy URL to check.
        
        Returns:
            True if healthy, False otherwise.
        """
        test_url = "https://httpbin.org/ip"
        
        try:
            connector = aiohttp.TCPConnector()
            
            async with aiohttp.ClientSession(connector=connector) as session:
                start_time = time.time()
                
                async with session.get(
                    test_url,
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    elapsed = (time.time() - start_time) * 1000
                    
                    if response.status == 200:
                        # Update proxy info
                        for proxy in self.proxies:
                            if proxy_url.startswith(proxy.url):
                                proxy.is_healthy = True
                                proxy.last_check = time.time()
                                proxy.avg_response_time_ms = elapsed
                                break
                        return True
                        
        except Exception as e:
            logger.debug(f"Proxy health check failed for {proxy_url}: {e}")
        
        # Mark as unhealthy
        for proxy in self.proxies:
            if proxy_url.startswith(proxy.url):
                proxy.is_healthy = False
                proxy.last_check = time.time()
                break
        
        return False
    
    async def check_all_proxies(self) -> Dict[str, bool]:
        """
        Check health of all proxies.
        
        Returns:
            Dictionary mapping proxy URL to health status.
        """
        results = {}
        
        tasks = [
            self.check_proxy_health(proxy.get_connector_url())
            for proxy in self.proxies
        ]
        
        health_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for proxy, health in zip(self.proxies, health_results):
            if isinstance(health, Exception):
                results[proxy.url] = False
            else:
                results[proxy.url] = health
        
        return results
    
    def get_healthy_proxies(self) -> List[str]:
        """
        Get list of healthy proxy URLs.
        
        Returns:
            List of healthy proxy URLs.
        """
        return [p.get_connector_url() for p in self.proxies if p.is_healthy]
    
    def get_stats(self) -> Dict[str, any]:
        """
        Get proxy pool statistics.
        
        Returns:
            Dictionary with proxy stats.
        """
        total = len(self.proxies)
        healthy = len([p for p in self.proxies if p.is_healthy])
        
        total_success = sum(p.success_count for p in self.proxies)
        total_failure = sum(p.failure_count for p in self.proxies)
        
        return {
            "total_proxies": total,
            "healthy_proxies": healthy,
            "unhealthy_proxies": total - healthy,
            "total_requests": total_success + total_failure,
            "success_count": total_success,
            "failure_count": total_failure,
            "overall_success_rate": (
                total_success / (total_success + total_failure)
                if (total_success + total_failure) > 0 else 0.0
            ),
        }
    
    def remove_proxy(self, proxy_url: str) -> bool:
        """
        Remove a proxy from the pool.
        
        Args:
            proxy_url: Proxy URL to remove.
        
        Returns:
            True if removed, False if not found.
        """
        for i, proxy in enumerate(self.proxies):
            if proxy.url == proxy_url or proxy_url.startswith(proxy.url):
                del self.proxies[i]
                logger.info(f"Removed proxy: {proxy_url}")
                return True
        return False
    
    def clear(self) -> None:
        """Remove all proxies."""
        self.proxies.clear()
        self._failed_proxies.clear()
        self._current_index = 0
        self._request_count = 0
