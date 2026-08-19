"""
Shared HTTP client helpers.
"""
import ssl
from functools import lru_cache

import aiohttp
import certifi


@lru_cache(maxsize=1)
def create_ssl_context() -> ssl.SSLContext:
    """Create a secure SSL context using certifi CA bundle (or system CAs if certifi is unavailable)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()



def create_connector(**kwargs) -> aiohttp.TCPConnector:
    """
    Create an aiohttp.TCPConnector with real certificate verification.

    Use this in place of `aiohttp.TCPConnector(ssl=False)`. Extra keyword
    arguments (limit, ttl_dns_cache, ...) are passed straight through.
    """
    return aiohttp.TCPConnector(ssl=create_ssl_context(), **kwargs)
