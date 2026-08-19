
from typing import Dict, Optional
from .base_scraper import BaseScraper
from .google_news_scraper import GoogleNewsScraper
from .rss_scraper import RSSScraper
from .api_scraper import APIScraper

class ScraperFactory:
    """Factory to create scrapers based on config"""
    
    @staticmethod
    def create_scraper(source_config: Dict) -> Optional[BaseScraper]:
        scraper_type = source_config.get('type', '').lower()
        
        if scraper_type == 'google_news':
            return GoogleNewsScraper(source_config)
        elif scraper_type == 'rss':
            return RSSScraper(source_config)
        elif scraper_type == 'api':
            return APIScraper(source_config)
        else:
            return None
