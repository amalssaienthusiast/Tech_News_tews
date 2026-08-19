
from .base_scraper import BaseScraper
import feedparser
from datetime import datetime
from typing import List, Dict
import asyncio

class RSSScraper(BaseScraper):
    """Generic RSS feed scraper"""
    
    async def fetch_news(self) -> List[Dict]:
        if not self.session:
            await self.initialize_session()
            
        try:
            async with self.session.get(self.url) as response:
                if response.status != 200:
                    self.logger.error(f"Failed to fetch RSS feed {self.url}: {response.status}")
                    return []
                content = await response.text()
                
                # Offload parsing to sync executor if needed, but feedparser is fast enough for small feeds
                feed = feedparser.parse(content)
                
                articles = []
                for entry in feed.entries:
                    try:
                        published_date = self._parse_date(entry.get('published', entry.get('updated', '')))
                        
                        article = {
                            'title': entry.get('title', ''),
                            'description': entry.get('summary', ''),
                            'content': entry.get('content', [{}])[0].get('value', '') if entry.get('content') else '',
                            'url': entry.get('link', ''),
                            'published_at': published_date,
                            'source': entry.get('source', {}).get('title', self.name),
                            'author': entry.get('author', ''),
                            'categories': [tag.term for tag in entry.get('tags', [])],
                            'media_url': self._extract_media_url(entry)
                        }
                        articles.append(article)
                    except Exception as e:
                        self.logger.warning(f"Error parsing entry: {str(e)}")
                
                return articles
        except Exception as e:
             self.logger.error(f"Error fetching RSS feed {self.url}: {str(e)}")
             return []
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse RSS date formats"""
        if not date_str:
            return datetime.utcnow()
            
        try:
            # Common RSS format
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str).replace(tzinfo=None) # naive UTC
        except Exception as e:
            self.logger.debug(f"_parse_date: suppressed {type(e).__name__}: {e}")
            try:
                # ISO format
                return datetime.fromisoformat(date_str.replace('Z', '+00:00')).replace(tzinfo=None)
            except Exception as e:
                self.logger.debug(f"_parse_date: suppressed {type(e).__name__}: {e}")
                return datetime.utcnow()
    
    def _extract_media_url(self, entry) -> str:
        """Extract media/thumbnail URL"""
        if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            return entry.media_thumbnail[0].get('url', '')
        elif hasattr(entry, 'enclosures') and entry.enclosures:
            for enclosure in entry.enclosures:
                if enclosure.get('type', '').startswith('image/'):
                    return enclosure.get('href', '')
        elif 'media_content' in entry:
             media = entry.media_content
             if media and isinstance(media, list):
                 return media[0].get('url', '')
        return ''
