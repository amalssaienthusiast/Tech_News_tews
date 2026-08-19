
from .base_scraper import BaseScraper
import json
from typing import List, Dict
from datetime import datetime

class APIScraper(BaseScraper):
    """API-based news scraper"""
    
    async def fetch_news(self) -> List[Dict]:
        if not self.session:
            await self.initialize_session()
            
        headers = {}
        
        # Add API key if required
        if self.source_config.get('api_key'):
            # Basic support for Bearer or X-Api-Key, extendable via config
            if 'twitter' in self.url:
                 headers['Authorization'] = f"Bearer {self.source_config['api_key']}"
            else:
                 headers['X-Api-Key'] = self.source_config['api_key']
                 headers['Authorization'] = f"{self.source_config['api_key']}" # Fallback
        
        # Add custom headers
        if self.source_config.get('headers'):
            headers.update(self.source_config['headers'])
        
        params = self.source_config.get('parameters', {})
        
        try:
            async with self.session.get(self.url, headers=headers, params=params) as response:
                if response.status != 200:
                    self.logger.error(f"API Request failed: {response.status} - {await response.text()}")
                    return []
                    
                data = await response.json()
                articles = self._parse_response(data)
                return articles
        except Exception as e:
            self.logger.error(f"Error fetching API {self.url}: {str(e)}")
            return []
    
    def _parse_response(self, data: Dict) -> List[Dict]:
        """Parse API response based on provider"""
        articles = []
        
        if 'articles' in data:  # NewsAPI format
            for item in data['articles']:
                article = {
                    'title': item.get('title', ''),
                    'description': item.get('description', ''),
                    'url': item.get('url', ''),
                    'published_at': self._parse_api_date(item.get('publishedAt', '')),
                    'source': item.get('source', {}).get('name', ''),
                    'author': item.get('author', ''),
                    'content': item.get('content', ''),
                    'media_url': item.get('urlToImage', '')
                }
                articles.append(article)
        
        elif 'results' in data:  # generic results format
            for item in data['results']:
                article = {
                    'title': item.get('title', ''),
                    'description': item.get('abstract', '') or item.get('description', ''),
                    'url': item.get('url', ''),
                    'published_at': self._parse_api_date(item.get('published_date', '') or item.get('created_at', '')),
                    'source': self.name,
                    'author': item.get('byline', ''),
                    'content': item.get('content', '')
                }
                articles.append(article)
        
        elif 'data' in data: # Twitter/X format often puts tweets in 'data'
             for item in data['data']:
                 # Very basic twitter parsing
                 article = {
                     'title': item.get('text', '')[:100], # Use first 100 chars as title
                     'description': item.get('text', ''),
                     'url': f"https://twitter.com/i/web/status/{item.get('id', '')}",
                     'published_at': self._parse_api_date(item.get('created_at', '')),
                     'source': 'Twitter',
                     'author': item.get('author_id', ''), # Requires expansion for real name
                 }
                 articles.append(article)

        return articles
    
    def _parse_api_date(self, date_str: str):
        """Parse various API date formats"""
        if not date_str:
            return datetime.utcnow()
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception as e:
            self.logger.debug(f"_parse_api_date: suppressed {type(e).__name__}: {e}")
            return datetime.utcnow()
