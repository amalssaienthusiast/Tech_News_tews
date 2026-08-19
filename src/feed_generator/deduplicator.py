
from typing import List, Dict
import re
from difflib import SequenceMatcher
from datetime import datetime

class Deduplicator:
    """Deduplicate articles across sources"""
    
    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold
        
    async def deduplicate(self, articles: List[Dict]) -> List[Dict]:
        """Remove duplicate articles"""
        unique_articles = []
        seen_ids = set()
        seen_titles = [] # List of tuples (cleaned_title, original_article) for similarity check
        
        # Sort by date so we keep the most recent version if duplicates exist? 
        # Actually usually we want to keep the one we found first or verify source priority.
        # Here we sort by published_at (newest first) to prioritize fresh content.
        sorted_articles = sorted(
            articles, 
            key=lambda x: x.get('published_at', datetime.min) if isinstance(x.get('published_at'), datetime) else datetime.min, 
            reverse=True
        )
        
        for article in sorted_articles:
            article_id = article.get('id', '')
            title = article.get('title', '').lower()
            
            # Check if exact duplicate ID
            if article_id in seen_ids:
                continue
            
            # Check if similar title exists
            if self._is_similar_title(title, seen_titles):
                continue
            
            seen_ids.add(article_id)
            seen_titles.append((self._clean_title(title), article))
            unique_articles.append(article)
        
        return unique_articles
    
    def _is_similar_title(self, title: str, seen_titles: List) -> bool:
        """Check if title is similar to any seen title"""
        clean_new = self._clean_title(title)
        
        # Optimization: only check against titles that are roughly the same length?
        # For now, check all. If buffer is large, this is O(N^2).
        # We limit buffer size in live_feed, so it should be fine.
        
        for clean_seen, _ in seen_titles:
            # Quick check: if lengths are vastly different, skip
            if abs(len(clean_new) - len(clean_seen)) > 20: 
                continue
                
            similarity = self._calculate_similarity(clean_new, clean_seen)
            if similarity > self.similarity_threshold:
                return True
        return False
    
    def _calculate_similarity(self, title1: str, title2: str) -> float:
        """Calculate similarity between two titles using SequenceMatcher"""
        return SequenceMatcher(None, title1, title2).ratio()
    
    def _clean_title(self, title: str) -> str:
        """Clean title for comparison"""
        # Remove special characters, extra spaces
        cleaned = re.sub(r'[^\w\s]', '', title)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned.strip().lower()
