"""
Elasticsearch Client for Full-Text Search.

Provides connection management, index operations, and search functionality.
Falls back gracefully when Elasticsearch is unavailable.
"""

import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from functools import lru_cache

logger = logging.getLogger(__name__)

# Check for Elasticsearch
try:
    from elasticsearch import Elasticsearch, AsyncElasticsearch
    from elasticsearch.exceptions import ConnectionError as ESConnectionError
    ELASTICSEARCH_AVAILABLE = True
except ImportError:
    ELASTICSEARCH_AVAILABLE = False
    logger.warning("Elasticsearch not installed. Full-text search disabled. Install with: pip install elasticsearch>=8.10.0")


# Article index mapping
ARTICLE_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {
            "analyzer": {
                "tech_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding", "tech_synonyms"],
                },
            },
            "filter": {
                "tech_synonyms": {
                    "type": "synonym",
                    "synonyms": [
                        "ai, artificial intelligence, machine learning, ml",
                        "api, application programming interface",
                        "js, javascript",
                        "ts, typescript",
                        "k8s, kubernetes",
                        "db, database",
                    ],
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "title": {
                "type": "text",
                "analyzer": "tech_analyzer",
                "fields": {
                    "keyword": {"type": "keyword"},
                },
            },
            "content": {
                "type": "text",
                "analyzer": "tech_analyzer",
            },
            "summary": {
                "type": "text",
                "analyzer": "tech_analyzer",
            },
            "url": {"type": "keyword"},
            "source": {"type": "keyword"},
            "source_api": {"type": "keyword"},
            "author": {"type": "keyword"},
            "published_at": {"type": "date"},
            "indexed_at": {"type": "date"},
            "tech_score": {"type": "float"},
            "keywords": {"type": "keyword"},
            "categories": {"type": "keyword"},
            "entities": {
                "properties": {
                    "companies": {"type": "keyword"},
                    "technologies": {"type": "keyword"},
                    "people": {"type": "keyword"},
                },
            },
        },
    },
}


class ElasticSearchClient:
    """
    Elasticsearch client for article indexing and search.
    
    Features:
    - Automatic index creation with tech-optimized mapping
    - Connection pooling and retry logic
    - Async and sync operation modes
    - Graceful fallback when ES unavailable
    """
    
    def __init__(
        self,
        hosts: Optional[List[str]] = None,
        index_name: Optional[str] = None,
        api_key: Optional[str] = None,
        cloud_id: Optional[str] = None,
    ):
        """
        Initialize Elasticsearch client.
        
        Args:
            hosts: ES host URLs. Falls back to ELASTICSEARCH_URL env var.
            index_name: Index name. Falls back to ELASTICSEARCH_INDEX env var.
            api_key: Optional API key for authentication.
            cloud_id: Optional Elastic Cloud ID.
        """
        self.hosts = hosts or [os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")]
        self.index_name = index_name or os.getenv("ELASTICSEARCH_INDEX", "tech_news_articles")
        self.api_key = api_key or os.getenv("ELASTICSEARCH_API_KEY")
        self.cloud_id = cloud_id or os.getenv("ELASTICSEARCH_CLOUD_ID")
        
        self._client: Optional["Elasticsearch"] = None
        self._async_client: Optional["AsyncElasticsearch"] = None
        self._connected = False
        
        if ELASTICSEARCH_AVAILABLE:
            self._initialize_client()
    
    def _initialize_client(self) -> bool:
        """Initialize the Elasticsearch client."""
        try:
            client_kwargs = {}
            
            if self.cloud_id:
                client_kwargs["cloud_id"] = self.cloud_id
            else:
                client_kwargs["hosts"] = self.hosts
            
            if self.api_key:
                client_kwargs["api_key"] = self.api_key
            
            # Sync client
            self._client = Elasticsearch(**client_kwargs)
            
            # Test connection
            if self._client.ping():
                self._connected = True
                logger.info(f"Connected to Elasticsearch at {self.hosts}")
                
                # Ensure index exists
                self._ensure_index()
                return True
            else:
                logger.warning("Elasticsearch ping failed")
                return False
                
        except Exception as e:
            logger.warning(f"Elasticsearch connection failed: {e}")
            self._connected = False
            return False
    
    def _ensure_index(self) -> None:
        """Create index if it doesn't exist."""
        if not self._client:
            return
        
        try:
            if not self._client.indices.exists(index=self.index_name):
                self._client.indices.create(
                    index=self.index_name,
                    body=ARTICLE_MAPPING,
                )
                logger.info(f"Created Elasticsearch index: {self.index_name}")
        except Exception as e:
            logger.error(f"Failed to create index: {e}")
    
    @property
    def is_available(self) -> bool:
        """Check if Elasticsearch is available."""
        return ELASTICSEARCH_AVAILABLE and self._connected
    
    def index_article(self, article: Dict[str, Any]) -> Optional[str]:
        """
        Index a single article.
        
        Args:
            article: Article dict with title, content, url, etc.
            
        Returns:
            Document ID if successful, None otherwise.
        """
        if not self.is_available:
            return None
        
        try:
            # Add indexing timestamp
            article["indexed_at"] = datetime.utcnow().isoformat()
            
            # Use URL hash as document ID for deduplication
            doc_id = self._generate_doc_id(article.get("url", ""))
            
            response = self._client.index(
                index=self.index_name,
                id=doc_id,
                document=article,
            )
            
            return response.get("_id")
            
        except Exception as e:
            logger.error(f"Failed to index article: {e}")
            return None
    
    def bulk_index(self, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Bulk index multiple articles.
        
        Args:
            articles: List of article dicts.
            
        Returns:
            Dict with success count and errors.
        """
        if not self.is_available or not articles:
            return {"indexed": 0, "errors": []}
        
        try:
            from elasticsearch.helpers import bulk
            
            # Prepare bulk actions
            actions = []
            for article in articles:
                article["indexed_at"] = datetime.utcnow().isoformat()
                doc_id = self._generate_doc_id(article.get("url", ""))
                
                actions.append({
                    "_index": self.index_name,
                    "_id": doc_id,
                    "_source": article,
                })
            
            success, errors = bulk(self._client, actions, raise_on_error=False)
            
            if errors:
                logger.warning(f"Bulk index had {len(errors)} errors")
                
            return {
                "indexed": success,
                "errors": errors[:10],  # Limit error list
            }
            
        except Exception as e:
            logger.error(f"Bulk index failed: {e}")
            return {"indexed": 0, "errors": [str(e)]}
    
    def search(
        self,
        query: str,
        filters: Dict[str, Any] = None,
        size: int = 20,
        from_: int = 0,
    ) -> Dict[str, Any]:
        """
        Search articles with full-text query.
        
        Args:
            query: Search query string.
            filters: Optional filters (source, date_range, min_score).
            size: Number of results.
            from_: Offset for pagination.
            
        Returns:
            Dict with hits, total count, and took time.
        """
        if not self.is_available:
            return {"hits": [], "total": 0, "took": 0}
        
        try:
            # Build query
            must = [
                {
                    "multi_match": {
                        "query": query,
                        "fields": ["title^3", "summary^2", "content", "keywords"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                    }
                }
            ]
            
            filter_clauses = []
            
            if filters:
                if "source" in filters:
                    filter_clauses.append({"term": {"source": filters["source"]}})
                
                if "min_score" in filters:
                    filter_clauses.append({
                        "range": {"tech_score": {"gte": filters["min_score"]}}
                    })
                
                if "date_from" in filters:
                    filter_clauses.append({
                        "range": {"published_at": {"gte": filters["date_from"]}}
                    })
                
                if "date_to" in filters:
                    filter_clauses.append({
                        "range": {"published_at": {"lte": filters["date_to"]}}
                    })
            
            body = {
                "query": {
                    "bool": {
                        "must": must,
                        "filter": filter_clauses,
                    }
                },
                "size": size,
                "from": from_,
                "sort": [
                    {"_score": {"order": "desc"}},
                    {"published_at": {"order": "desc"}},
                ],
                "highlight": {
                    "fields": {
                        "title": {},
                        "summary": {},
                        "content": {"fragment_size": 200},
                    }
                },
            }
            
            response = self._client.search(index=self.index_name, body=body)
            
            hits = []
            for hit in response["hits"]["hits"]:
                article = hit["_source"]
                article["_score"] = hit["_score"]
                article["_highlights"] = hit.get("highlight", {})
                hits.append(article)
            
            return {
                "hits": hits,
                "total": response["hits"]["total"]["value"],
                "took": response["took"],
            }
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {"hits": [], "total": 0, "took": 0, "error": str(e)}
    
    def delete_index(self) -> bool:
        """Delete the index (use with caution)."""
        if not self.is_available:
            return False
        
        try:
            self._client.indices.delete(index=self.index_name)
            logger.info(f"Deleted index: {self.index_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete index: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        if not self.is_available:
            return {"available": False}
        
        try:
            stats = self._client.indices.stats(index=self.index_name)
            return {
                "available": True,
                "doc_count": stats["_all"]["primaries"]["docs"]["count"],
                "size_bytes": stats["_all"]["primaries"]["store"]["size_in_bytes"],
                "index_name": self.index_name,
            }
        except Exception as e:
            return {"available": True, "error": str(e)}
    
    def _generate_doc_id(self, url: str) -> str:
        """Generate document ID from URL."""
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()


@lru_cache(maxsize=1)
def get_search_client() -> ElasticSearchClient:
    """Get or create singleton search client."""
    return ElasticSearchClient()
