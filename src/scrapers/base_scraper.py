
import asyncio
import aiohttp
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Any
import hashlib

from src.utils.http import create_connector

class BaseScraper(ABC):
    def __init__(self, source_config: Dict):
        self.source_config = source_config
        self.name = source_config.get('name', 'Unknown')
        self.url = source_config.get('url')
        self.refresh_rate = source_config.get('refresh_rate', 300)
        self.last_scraped = None
        self.logger = logging.getLogger(f"scraper.{self.name}")
        self.session = None

    async def initialize_session(self):
        """Initialize async session"""
        if not self.session:
            connector = create_connector()
            self.session = aiohttp.ClientSession(
                connector=connector,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; NewsAggregator/1.0)',
                    'Accept': 'application/json, text/xml, */*',
                    'Accept-Language': 'en-US,en;q=0.9'
                }
            )
    
    @abstractmethod
    async def fetch_news(self) -> List[Dict]:
        """Fetch news from specific source"""
        pass
    
    def generate_id(self, title: str, source: str, published_at: datetime) -> str:
        """Generate unique ID for article"""
        # Handle cases where published_at might be None or a string if not parsed correctly yet, 
        # though subclasses should return datetime.
        date_str = published_at.isoformat() if isinstance(published_at, datetime) else str(published_at)
        content = f"{title}_{source}_{date_str}"
        return hashlib.md5(content.encode()).hexdigest()
    
    async def scrape(self) -> List[Dict]:
        """Main scraping method"""
        try:
            await self.initialize_session()
            articles = await self.fetch_news()
            self.last_scraped = datetime.utcnow()
            
            # Add metadata
            for article in articles:
                article['scraper_name'] = self.name
                article['source_url'] = self.url
                article['scraped_at'] = datetime.utcnow().isoformat()
                
                # Ensure published_at is present
                if 'published_at' not in article or not article['published_at']:
                     article['published_at'] = datetime.utcnow()

                article['id'] = self.generate_id(
                    article.get('title', ''),
                    self.name,
                    article.get('published_at')
                )
            
            self.logger.info(f"Scraped {len(articles)} articles from {self.name}")
            return articles
            
        except Exception as e:
            self.logger.error(f"Error scraping {self.name}: {str(e)}")
            return []
    
    async def close(self):
        """Close session"""
        if self.session:
            await self.session.close()
            self.session = None
