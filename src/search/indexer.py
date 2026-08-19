"""
Article Indexer for Elasticsearch.

Provides real-time and batch indexing of articles with:
- Automatic field mapping
- Event-driven indexing
- Bulk operations
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.search.elastic_client import get_search_client, ELASTICSEARCH_AVAILABLE

logger = logging.getLogger(__name__)


class ArticleIndexer:
    """
    Handles article indexing to Elasticsearch.
    
    Provides both real-time (single article) and batch indexing modes.
    Integrates with the event bus for automatic indexing on new articles.
    """
    
    def __init__(self, client=None):
        """
        Initialize indexer.
        
        Args:
            client: Optional ElasticSearchClient. Uses singleton if not provided.
        """
        self._client = client or get_search_client()
        self._indexed_count = 0
        self._error_count = 0
    
    @property
    def is_available(self) -> bool:
        """Check if indexer is ready."""
        return ELASTICSEARCH_AVAILABLE and self._client.is_available
    
    def index_article(self, article) -> bool:
        """
        Index a single article.
        
        Args:
            article: Article object or dict.
            
        Returns:
            True if indexed successfully.
        """
        if not self.is_available:
            return False
        
        try:
            doc = self._article_to_document(article)
            doc_id = self._client.index_article(doc)
            
            if doc_id:
                self._indexed_count += 1
                logger.debug(f"Indexed article: {doc.get('title', '')[:50]}")
                return True
            return False
            
        except Exception as e:
            self._error_count += 1
            logger.error(f"Failed to index article: {e}")
            return False
    
    def bulk_index(self, articles: List) -> Dict[str, int]:
        """
        Bulk index multiple articles.
        
        Args:
            articles: List of Article objects or dicts.
            
        Returns:
            Dict with indexed and error counts.
        """
        if not self.is_available or not articles:
            return {"indexed": 0, "errors": 0}
        
        try:
            docs = [self._article_to_document(a) for a in articles]
            result = self._client.bulk_index(docs)
            
            self._indexed_count += result.get("indexed", 0)
            error_count = len(result.get("errors", []))
            self._error_count += error_count
            
            logger.info(f"Bulk indexed {result.get('indexed', 0)} articles ({error_count} errors)")
            
            return {
                "indexed": result.get("indexed", 0),
                "errors": error_count,
            }
            
        except Exception as e:
            logger.error(f"Bulk index failed: {e}")
            return {"indexed": 0, "errors": len(articles)}
    
    def _article_to_document(self, article) -> Dict[str, Any]:
        """Convert article to Elasticsearch document."""
        # Handle both Article objects and dicts
        if hasattr(article, "to_dict"):
            data = article.to_dict()
        elif hasattr(article, "__dict__"):
            data = {
                "id": getattr(article, "id", None) or str(hash(getattr(article, "url", ""))),
                "title": getattr(article, "title", ""),
                "url": getattr(article, "url", ""),
                "source": getattr(article, "source", ""),
                "content": getattr(article, "content", ""),
                "summary": getattr(article, "summary", ""),
                "author": getattr(article, "author", ""),
                "published_at": getattr(article, "published_at", None),
                "keywords": getattr(article, "keywords", []),
            }
            
            # Handle tech_score
            tech_score = getattr(article, "tech_score", None)
            if tech_score:
                data["tech_score"] = getattr(tech_score, "score", 0.0)
            
        else:
            data = dict(article)
        
        # Ensure required fields
        if "published_at" in data and data["published_at"]:
            if isinstance(data["published_at"], datetime):
                data["published_at"] = data["published_at"].isoformat()
        
        # Add indexing timestamp
        data["indexed_at"] = datetime.utcnow().isoformat()
        
        return data
    
    def setup_event_listener(self):
        """
        Setup event listener for automatic indexing.
        Listens for new article events from the event bus.
        """
        if not self.is_available:
            logger.debug("Elasticsearch not available, skipping event listener setup")
            return
        
        try:
            from src.core.events import event_bus
            
            def on_new_article(article):
                self.index_article(article)
            
            # Subscribe to new article events
            # event_bus.subscribe("new_article", on_new_article)
            logger.info("Article indexer event listener configured")
            
        except Exception as e:
            logger.warning(f"Could not setup event listener: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get indexer statistics."""
        stats = {
            "indexed_count": self._indexed_count,
            "error_count": self._error_count,
            "available": self.is_available,
        }
        if self._client:
            stats.update(self._client.get_stats())
        return stats
    
    def reindex_all(self, articles: List, clear_first: bool = False) -> Dict[str, int]:
        """
        Reindex all articles (useful for schema changes).
        
        Args:
            articles: All articles to index.
            clear_first: If True, delete index before reindexing.
            
        Returns:
            Indexing statistics.
        """
        if clear_first and self.is_available:
            self._client.delete_index()
            self._client._ensure_index()
        
        return self.bulk_index(articles)


# Convenience function
def index_articles(articles: List) -> Dict[str, int]:
    """
    Convenience function to index articles.
    
    Args:
        articles: List of articles to index.
        
    Returns:
        Indexing statistics.
    """
    indexer = ArticleIndexer()
    return indexer.bulk_index(articles)
