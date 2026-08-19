import asyncio
import aiohttp
from typing import Dict, List, Optional, Any
import json
import re
from urllib.parse import quote
import logging

from src.utils.http import create_connector

logger = logging.getLogger(__name__)


class MultiSourceReconstructor:
    """
    Reconstructs full content by aggregating from multiple public sources:
    - RSS feeds
    - Meta tags & Twitter Cards
    - Google Cache
    - Archive.org
    - Outline.com / textise dot iitty
    """
    
    SOURCES = {
        'rss': 'https://r.jina.ai/http://{domain}/rss',
        'twitter_card': 'https://r.jina.ai/http://{url}',
        'google_cache': 'https://webcache.googleusercontent.com/search?q=cache:{url}',
        'archive': 'https://web.archive.org/web/{timestamp}/{url}',
        'textise': 'https://r.jina.ai/http://{url}'
    }

    async def fetch_source(self, session: aiohttp.ClientSession, source_type: str, 
                          url: str, domain: str) -> Optional[str]:
        """Fetch content from a specific source"""
        
        try:
            if source_type == 'rss':
                feed_url = self.SOURCES['rss'].format(domain=domain)
                logger.info(f"Fetching RSS feed: {feed_url}")
                async with session.get(feed_url, timeout=10) as response:
                    if response.status == 200:
                        return await response.text()
            
            elif source_type == 'twitter_card':
                # Jina AI summarizer often gets past paywalls
                card_url = self.SOURCES['twitter_card'].format(url=quote(url, safe=''))
                logger.info(f"Fetching via Jina AI: {card_url}")
                async with session.get(card_url, timeout=10) as response:
                    if response.status == 200:
                        return await response.text()
            
            elif source_type == 'google_cache':
                cache_url = self.SOURCES['google_cache'].format(url=quote(url, safe=''))
                logger.info(f"Fetching Google Cache: {cache_url}")
                async with session.get(cache_url, timeout=10) as response:
                    if response.status == 200:
                        return await response.text()
            
            elif source_type == 'archive':
                # Get latest snapshot
                archive_check = f"https://archive.org/wayback/available?url={url}"
                async with session.get(archive_check, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('archived_snapshots', {}).get('closest'):
                            timestamp = data['archived_snapshots']['closest']['timestamp']
                            archive_url = self.SOURCES['archive'].format(
                                timestamp=timestamp, url=url
                            )
                            logger.info(f"Fetching Archive.org: {archive_url}")
                            async with session.get(archive_url, timeout=10) as resp:
                                if resp.status == 200:
                                    return await resp.text()
            
            elif source_type == 'textise':
                text_url = self.SOURCES['textise'].format(url=quote(url, safe=''))
                logger.info(f"Fetching text-only version: {text_url}")
                async with session.get(text_url, timeout=10) as response:
                    if response.status == 200:
                        return await response.text()
        
        except Exception as e:
            logger.warning(f"Source {source_type} failed: {e}")
        
        return None

    def _extract_from_rss(self, rss_content: str, url: str) -> Optional[str]:
        """Extract full content from RSS feed entry"""
        try:
            # Look for article link in RSS
            article_pattern = rf'<link>{re.escape(url)}</link>.*?<content:encoded>(.*?)</content:encoded>'
            match = re.search(article_pattern, rss_content, re.S | re.I)
            
            if match:
                content = match.group(1)
                # Unescape HTML entities
                content = re.sub(r'<!\[CDATA\[(.*?)\]\]>', lambda m: m.group(1), content, flags=re.S)
                if len(content) > 1000:
                    logger.info("Extracted full content from RSS feed")
                    return content
            
            # Fallback to description
            desc_pattern = rf'<link>{re.escape(url)}</link>.*?<description>(.*?)</description>'
            desc_match = re.search(desc_pattern, rss_content, re.S | re.I)
            if desc_match:
                content = desc_match.group(1)
                if len(content) > 500:
                    logger.info("Extracted description from RSS feed")
                    return content
        
        except Exception as e:
            logger.error(f"RSS extraction failed: {e}")
        
        return None

    def _reconstruct_from_fragments(self, fragments: List[str]) -> str:
        """Smart reconstruction using semantic chunking"""
        # Remove duplicates while preserving order
        seen = set()
        unique_fragments = []
        
        for frag in fragments:
            # Create hash of first/last 200 chars to detect duplicates
            signature = hash(frag[:200] + frag[-200:])
            if signature not in seen and len(frag) > 200:
                seen.add(signature)
                unique_fragments.append(frag)
        
        # Sort by length (longest first, as it's likely the full article)
        unique_fragments.sort(key=len, reverse=True)
        
        if unique_fragments:
            logger.info(f"Reconstructed content from {len(unique_fragments)} sources")
            return unique_fragments[0]  # Return longest fragment
        
        return ""

    async def reconstruct(self, url: str) -> Optional[str]:
        """
        Orchestrate multi-source reconstruction attempt
        """
        domain = '/'.join(url.split('/')[2:])
        fragments = []
        
        # Create a session with SSL disabled to avoid certificate errors on macOS
        connector = create_connector()
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                self.fetch_source(session, 'rss', url, domain),
                self.fetch_source(session, 'twitter_card', url, domain),
                self.fetch_source(session, 'google_cache', url, domain),
                self.fetch_source(session, 'archive', url, domain),
                self.fetch_source(session, 'textise', url, domain)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                source_type = ['rss', 'twitter_card', 'google_cache', 'archive', 'textise'][i]
                
                if isinstance(result, Exception):
                    logger.error(f"Source {source_type} error: {result}")
                    continue
                
                if not result:
                    continue
                
                # Extract content based on source type
                if source_type == 'rss':
                    content = self._extract_from_rss(result, url)
                    if content:
                        fragments.append(content)
                
                elif source_type in ['twitter_card', 'textise']:
                    # These often return clean text
                    if len(result) > 1000 and '---' not in result[:100]:
                        fragments.append(result)
                
                else:  # cache/archive
                    # Run through content extractor to clean
                    # Import locally to avoid circular imports
                    try:
                        from src.engine.deep_scraper import ContentExtractor
                        # ContentExtractor is static
                        content = ContentExtractor.extract(result, url)
                        # ContentExtractor returns dict, need 'content' string
                        if isinstance(content, dict) and content.get('content'):
                            text = content['content']
                            if len(text) > 1000:
                                fragments.append(text)
                    except ImportError:
                         # Fallback if ContentExtractor unavailable
                        logger.warning("ContentExtractor unavailable for reconstruction cleaning")
                        if len(result) > 2000:
                            fragments.append(result)

        
        if fragments:
            return self._reconstruct_from_fragments(fragments)
        
        return None
