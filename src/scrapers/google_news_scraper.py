
from .base_scraper import BaseScraper
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime
import re
from typing import Dict, List, Optional
import feedparser
from email.utils import parsedate_to_datetime

class GoogleNewsScraper(BaseScraper):
    """Scraper for Google News RSS and web scraping"""
    
    async def fetch_news(self) -> List[Dict]:
        articles = []
        
        # Method 1: RSS Feed (Prioritized as it's more stable)
        if 'rss' in self.url:
             rss_articles = await self._fetch_rss()
             articles.extend(rss_articles)
        else:
            # Method 2: Direct web scraping for latest news (Fallback or if configured)
            # Note: Web scraping Google News often requires JS rendering or heavy anti-bot evasion.
            # We will try a lightweight approach.
            web_articles = await self._scrape_website()
            articles.extend(web_articles)
        
        return articles
    
    async def _fetch_rss(self) -> List[Dict]:
        """Fetch from Google News RSS"""
        if not self.session:
            await self.initialize_session()
            
        try:
            async with self.session.get(self.url) as response:
                content = await response.text()
                feed = feedparser.parse(content)
                
                articles = []
                for entry in feed.entries[:50]:  # Get latest 50
                    try:
                        published_at = self._parse_date(entry.get('published', ''))
                        
                        article = {
                            'title': entry.get('title', ''),
                            'description': entry.get('summary', ''),
                            'url': entry.get('link', ''),
                            'published_at': published_at,
                            'source': entry.get('source', {}).get('title', 'Google News'),
                            'category': 'General', # RSS doesn't always provide category per item easily
                            'media_url': '' # Google RSS often doesn't have direct media links in standard fields
                        }
                        articles.append(article)
                    except Exception as e:
                        self.logger.warning(f"Error parsing Google News RSS entry: {e}")
                
                return articles
        except Exception as e:
            self.logger.error(f"Error fetching Google News RSS: {e}")
            return []
    
    async def _scrape_website(self) -> List[Dict]:
        """Direct website scraping for real-time news"""
        # NOTE: This is brittle and might be blocked. 
        # For this implementation, we will focus on RSS success or return empty if blocked.
        return []
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse various date formats"""
        try:
            return parsedate_to_datetime(date_str).replace(tzinfo=None)
        except Exception as e:
            self.logger.debug(f"_parse_date: suppressed {type(e).__name__}: {e}")
            return datetime.utcnow()
