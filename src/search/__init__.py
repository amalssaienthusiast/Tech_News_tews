"""
Search Module for Tech News Scraper.

Provides Elasticsearch-powered full-text search:
- Article indexing
- Query building with fuzzy matching
- Filter by source, date, score
"""

from src.search.elastic_client import (
    ElasticSearchClient,
    get_search_client,
    ELASTICSEARCH_AVAILABLE,
)
from src.search.query_builder import SearchQueryBuilder
from src.search.indexer import ArticleIndexer

__all__ = [
    "ElasticSearchClient",
    "get_search_client",
    "SearchQueryBuilder",
    "ArticleIndexer",
    "ELASTICSEARCH_AVAILABLE",
]
