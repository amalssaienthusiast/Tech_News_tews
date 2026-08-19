
import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Dict
from collections import defaultdict
import logging
from .deduplicator import Deduplicator

class LiveFeedGenerator:
    """Generates real-time live feed from multiple sources"""
    
    def __init__(self):
        self.logger = logging.getLogger('live_feed')
        self.deduplicator = Deduplicator()
        self.articles_buffer = []
        self.max_buffer_size = 1000
        
    async def generate_feed(self, articles_list: List[List[Dict]]) -> Dict:
        """Generate unified live feed"""
        
        # Flatten all articles
        all_articles = []
        for articles in articles_list:
            all_articles.extend(articles)
        
        self.logger.info(f"Processing {len(all_articles)} total articles")
        
        # Deduplicate
        unique_articles = await self.deduplicator.deduplicate(all_articles)
        
        # Sort by recency (newest first)
        sorted_articles = sorted(
            unique_articles,
            key=lambda x: x.get('published_at', datetime.min) if isinstance(x.get('published_at'), datetime) else datetime.min,
            reverse=True
        )
        
        # Filter only recent articles (last 24 hours)
        recent_articles = self._filter_recent(sorted_articles)
        
        # Categorize articles
        categorized = self._categorize_articles(recent_articles)
        
        # Update buffer for trending analysis (keeps history)
        self._update_buffer(recent_articles)
        
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'total_articles': len(recent_articles),
            'articles': recent_articles[:100],  # Return top 100
            'categories': categorized,
            'trending': self._get_trending_topics()
        }
    
    def _filter_recent(self, articles: List[Dict], hours: int = 24) -> List[Dict]:
        """Filter articles from last N hours"""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        filtered = []
        for article in articles:
            pub = article.get('published_at')
            if pub and isinstance(pub, datetime) and pub > cutoff:
                filtered.append(article)
        return filtered
    
    def _categorize_articles(self, articles: List[Dict]) -> Dict:
        """Categorize articles by source and topic"""
        categories = defaultdict(list)
        categories['by_source'] = [] # schema defines as list of dicts, or dict of lists? User code implies list of dicts for 'by_source' summary?
        # Actually user code was:
        # categories['by_source'].append({'source':..., 'title':...})
        # So 'by_source' is a list of metadata, not grouped articles. 
        # But 'topic' keys hold lists of full articles.
        
        # Let's clean this up to be more useful: 
        # categories = { 'Politics': [...], 'Tech': [...], 'by_source': { 'CNN': 5, 'BBC': 10 } } ??
        # User code:
        # categories['by_source'].append({...})
        # categories[topic].append(article)
        
        source_summary = []
        
        for article in articles:
            # Source summary
            source_summary.append({
                'source': article.get('source', 'Unknown'),
                'title': article.get('title', ''),
                'url': article.get('url', ''),
                'id': article.get('id', '')
            })
            
            # Categorize by detected topic
            topic = self._detect_topic(article)
            categories[topic].append(article)
        
        result = dict(categories)
        result['by_source'] = source_summary 
        return result
    
    def _detect_topic(self, article: Dict) -> str:
        """Simple topic detection from title"""
        title = article.get('title', '').lower()
        description = article.get('description', '').lower()
        content = f"{title} {description}"
        
        keywords = {
            'politics': ['election', 'president', 'congress', 'senate', 'policy', 'vote', 'law'],
            'technology': ['tech', 'ai', 'software', 'apple', 'google', 'microsoft', 'app', 'cyber', 'data', 'robot'],
            'business': ['stock', 'market', 'economy', 'business', 'company', 'startup', 'money', 'finance'],
            'sports': ['sport', 'game', 'team', 'player', 'win', 'loss', 'cup', 'league'],
            'entertainment': ['movie', 'tv', 'celebrity', 'music', 'film', 'star', 'hollywood'],
            'science': ['space', 'nasa', 'climate', 'science', 'research', 'study', 'biology']
        }
        
        for topic, words in keywords.items():
            if any(word in content for word in words):
                return topic.capitalize()  # Return "Technology" not "technology"
        
        return 'General'
    
    def _update_buffer(self, new_articles: List[Dict]):
        """Update rolling buffer of articles"""
        # Add new articles not already in buffer
        existing_ids = {a.get('id') for a in self.articles_buffer}
        for a in new_articles:
            if a.get('id') not in existing_ids:
                self.articles_buffer.append(a)
        
        # Keep only recent articles in buffer
        cutoff = datetime.utcnow() - timedelta(hours=24)
        self.articles_buffer = [
            article for article in self.articles_buffer
            if isinstance(article.get('published_at'), datetime) and article.get('published_at') > cutoff
        ]
        
        # Limit buffer size (keep newest)
        if len(self.articles_buffer) > self.max_buffer_size:
            self.articles_buffer.sort(key=lambda x: x.get('published_at'), reverse=True)
            self.articles_buffer = self.articles_buffer[:self.max_buffer_size]
    
    def _get_trending_topics(self) -> List[Dict]:
        """Identify trending topics from buffer"""
        # Simple trending detection based on frequency
        word_counts = defaultdict(int)
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'this', 'that', 'from', 'as', 'it', 'its', 'new', 'after', 'up', 'out', 'over', 'says', 'will', 'has', 'have', 'more', 'about', 'who', 'what', 'where', 'when', 'why', 'how'}
        
        for article in self.articles_buffer[-200:]:  # Check last 200 items for trends
            title_words = re.findall(r'\w+', article.get('title', '').lower())
            for word in title_words:
                if len(word) > 3 and word not in stopwords:
                    word_counts[word] += 1
        
        trending = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        return [{'word': word, 'count': count} for word, count in trending]
