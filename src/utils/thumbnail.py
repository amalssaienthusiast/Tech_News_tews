"""
High-Speed Asynchronous OpenGraph Thumbnail Resolver.

Extracts rich preview images and OpenGraph thumbnails from article URLs
when feeds omit media:thumbnail or enclosure tags.
"""

import asyncio
import logging
import re
from typing import Optional, Any
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# In-memory thumbnail cache (URL -> image_url)
_THUMBNAIL_CACHE: dict[str, Optional[str]] = {}
_CACHE_MAX = 5000


def _clean_image_url(base_url: str, img_url: Any) -> Optional[str]:
    """Validate and resolve relative image URLs."""
    if not img_url:
        return None
    
    if isinstance(img_url, list):
        img_url = img_url[0] if img_url else None
        if not img_url:
            return None
            
    img_url = str(img_url).strip()
    if not img_url:
        return None

    # Ignore tracking pixels and common placeholder images
    lower = img_url.lower()
    if any(b in lower for b in [
        "1x1", "pixel", "tracker", "spacer.gif", "feedburner", "favicon",
        "avatar", "logo-small", "blank.png", "data:image"
    ]):
        return None

    # Resolve relative URL
    if not (img_url.startswith("http://") or img_url.startswith("https://")):
        img_url = urljoin(base_url, img_url)

    if img_url.startswith("http://") or img_url.startswith("https://"):
        return img_url
    return None


async def resolve_og_thumbnail(
    url: str,
    session: Optional[aiohttp.ClientSession] = None,
    timeout_seconds: float = 3.0,
) -> Optional[str]:
    """
    Fast extraction of og:image or twitter:image from article URL.
    Only reads the first 40KB of the HTML <head> for maximum speed.
    """
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return None

    from src.security.acquisition_policy import is_safe_acquisition_target
    if not is_safe_acquisition_target(url):
        logger.debug(f"Thumbnail resolution rejected prohibited URL '{url}'")
        return None

    if url in _THUMBNAIL_CACHE:
        return _THUMBNAIL_CACHE[url]

    # Manage cache size
    if len(_THUMBNAIL_CACHE) > _CACHE_MAX:
        # Discard oldest half
        for k in list(_THUMBNAIL_CACHE.keys())[: _CACHE_MAX // 2]:
            del _THUMBNAIL_CACHE[k]

    should_close_session = False
    if session is None or session.closed:
        connector = aiohttp.TCPConnector()
        session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
            },
        )
        should_close_session = True

    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                _THUMBNAIL_CACHE[url] = None
                return None

            # Stream up to 250KB to find <head> tags and fallback <img> tags in body
            content_chunks = []
            bytes_read = 0
            async for chunk in resp.content.iter_chunked(8192):
                content_chunks.append(chunk)
                bytes_read += len(chunk)
                if bytes_read >= 256000:
                    break

            raw_html = b"".join(content_chunks).decode("utf-8", errors="ignore")
            soup = BeautifulSoup(raw_html, "html.parser")

            # 1. Check OpenGraph image
            og_img = soup.find("meta", property=re.compile(r"^og:image", re.I))
            if og_img and og_img.get("content"):
                cleaned = _clean_image_url(url, og_img["content"])
                if cleaned:
                    _THUMBNAIL_CACHE[url] = cleaned
                    return cleaned

            # 2. Check Twitter card image
            tw_img = soup.find("meta", attrs={"name": re.compile(r"^twitter:image", re.I)})
            if tw_img and tw_img.get("content"):
                cleaned = _clean_image_url(url, tw_img["content"])
                if cleaned:
                    _THUMBNAIL_CACHE[url] = cleaned
                    return cleaned

            # 3. Check schema.org image or link rel=image_src
            link_img = soup.find("link", rel=re.compile(r"image_src", re.I))
            if link_img and link_img.get("href"):
                cleaned = _clean_image_url(url, link_img["href"])
                if cleaned:
                    _THUMBNAIL_CACHE[url] = cleaned
                    return cleaned

            # 4. Fallback: Check for the first reasonable <img> tag in the HTML body
            for img in soup.find_all("img"):
                img_src = img.get("src") or img.get("data-src")
                if img_src:
                    cleaned = _clean_image_url(url, img_src)
                    if cleaned:
                        _THUMBNAIL_CACHE[url] = cleaned
                        return cleaned

    except Exception:
        pass
    finally:
        if should_close_session:
            await session.close()

    _THUMBNAIL_CACHE[url] = None
    return None
