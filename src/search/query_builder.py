"""
Search Query Builder for Elasticsearch.

Provides fluent API for building complex search queries with:
- Fuzzy matching
- Phrase matching
- Filters (source, date, score)
- Aggregations
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta


class SearchQueryBuilder:
    """
    Fluent query builder for Elasticsearch searches.
    
    Usage:
        query = (SearchQueryBuilder()
            .text("artificial intelligence")
            .fuzzy(True)
            .filter_source("TechCrunch")
            .filter_date_range(days=7)
            .sort_by_relevance()
            .build())
    """
    
    def __init__(self):
        self._text_query: Optional[str] = None
        self._fields: List[str] = ["title^3", "summary^2", "content", "keywords"]
        self._fuzzy: bool = True
        self._filters: List[Dict[str, Any]] = []
        self._must_not: List[Dict[str, Any]] = []
        self._sort: List[Dict[str, Any]] = []
        self._size: int = 20
        self._from: int = 0
        self._highlight: bool = True
        self._aggregations: Dict[str, Any] = {}
        self._min_score: Optional[float] = None
    
    def text(self, query: str) -> "SearchQueryBuilder":
        """Set the main text query."""
        self._text_query = query
        return self
    
    def fields(self, field_list: List[str]) -> "SearchQueryBuilder":
        """Set fields to search with optional boosts (e.g., 'title^3')."""
        self._fields = field_list
        return self
    
    def fuzzy(self, enabled: bool = True) -> "SearchQueryBuilder":
        """Enable/disable fuzzy matching."""
        self._fuzzy = enabled
        return self
    
    def filter_source(self, source: str) -> "SearchQueryBuilder":
        """Filter by source name."""
        self._filters.append({"term": {"source": source}})
        return self
    
    def filter_sources(self, sources: List[str]) -> "SearchQueryBuilder":
        """Filter by multiple sources."""
        self._filters.append({"terms": {"source": sources}})
        return self
    
    def filter_source_api(self, api: str) -> "SearchQueryBuilder":
        """Filter by source API (google, bing, twitter, etc.)."""
        self._filters.append({"term": {"source_api": api}})
        return self
    
    def filter_date_range(
        self,
        days: Optional[int] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> "SearchQueryBuilder":
        """Filter by date range."""
        if days:
            date_from = datetime.utcnow() - timedelta(days=days)
        
        range_filter = {"range": {"published_at": {}}}
        
        if date_from:
            range_filter["range"]["published_at"]["gte"] = date_from.isoformat()
        if date_to:
            range_filter["range"]["published_at"]["lte"] = date_to.isoformat()
        
        if range_filter["range"]["published_at"]:
            self._filters.append(range_filter)
        
        return self
    
    def filter_min_score(self, min_score: float) -> "SearchQueryBuilder":
        """Filter by minimum tech score."""
        self._filters.append({"range": {"tech_score": {"gte": min_score}}})
        return self
    
    def filter_keywords(self, keywords: List[str]) -> "SearchQueryBuilder":
        """Filter articles containing specific keywords."""
        self._filters.append({"terms": {"keywords": keywords}})
        return self
    
    def filter_entities(
        self,
        companies: Optional[List[str]] = None,
        technologies: Optional[List[str]] = None,
    ) -> "SearchQueryBuilder":
        """Filter by mentioned entities."""
        if companies:
            self._filters.append({"terms": {"entities.companies": companies}})
        if technologies:
            self._filters.append({"terms": {"entities.technologies": technologies}})
        return self
    
    def exclude_source(self, source: str) -> "SearchQueryBuilder":
        """Exclude a specific source."""
        self._must_not.append({"term": {"source": source}})
        return self
    
    def min_query_score(self, score: float) -> "SearchQueryBuilder":
        """Set minimum relevance score for results."""
        self._min_score = score
        return self
    
    def sort_by_relevance(self) -> "SearchQueryBuilder":
        """Sort by relevance score (default)."""
        self._sort = [
            {"_score": {"order": "desc"}},
            {"published_at": {"order": "desc"}},
        ]
        return self
    
    def sort_by_date(self, ascending: bool = False) -> "SearchQueryBuilder":
        """Sort by publication date."""
        self._sort = [
            {"published_at": {"order": "asc" if ascending else "desc"}},
        ]
        return self
    
    def sort_by_tech_score(self) -> "SearchQueryBuilder":
        """Sort by tech relevance score."""
        self._sort = [
            {"tech_score": {"order": "desc"}},
            {"published_at": {"order": "desc"}},
        ]
        return self
    
    def paginate(self, page: int = 1, per_page: int = 20) -> "SearchQueryBuilder":
        """Set pagination."""
        self._size = per_page
        self._from = (page - 1) * per_page
        return self
    
    def size(self, n: int) -> "SearchQueryBuilder":
        """Set result size."""
        self._size = n
        return self
    
    def skip(self, n: int) -> "SearchQueryBuilder":
        """Skip first n results."""
        self._from = n
        return self
    
    def highlight(self, enabled: bool = True) -> "SearchQueryBuilder":
        """Enable/disable result highlighting."""
        self._highlight = enabled
        return self
    
    def aggregate_by_source(self) -> "SearchQueryBuilder":
        """Add source aggregation."""
        self._aggregations["sources"] = {
            "terms": {"field": "source", "size": 20}
        }
        return self
    
    def aggregate_by_date(self, interval: str = "day") -> "SearchQueryBuilder":
        """Add date histogram aggregation."""
        self._aggregations["dates"] = {
            "date_histogram": {
                "field": "published_at",
                "calendar_interval": interval,
            }
        }
        return self
    
    def build(self) -> Dict[str, Any]:
        """Build the final Elasticsearch query."""
        # Build main query
        if self._text_query:
            must = [
                {
                    "multi_match": {
                        "query": self._text_query,
                        "fields": self._fields,
                        "type": "best_fields",
                        **({"fuzziness": "AUTO"} if self._fuzzy else {}),
                    }
                }
            ]
        else:
            must = [{"match_all": {}}]
        
        # Build bool query
        bool_query = {
            "must": must,
        }
        
        if self._filters:
            bool_query["filter"] = self._filters
        
        if self._must_not:
            bool_query["must_not"] = self._must_not
        
        query = {
            "query": {"bool": bool_query},
            "size": self._size,
            "from": self._from,
        }
        
        if self._sort:
            query["sort"] = self._sort
        
        if self._min_score is not None:
            query["min_score"] = self._min_score
        
        if self._highlight:
            query["highlight"] = {
                "fields": {
                    "title": {},
                    "summary": {},
                    "content": {"fragment_size": 200},
                }
            }
        
        if self._aggregations:
            query["aggs"] = self._aggregations
        
        return query


# Convenience function for simple searches
def quick_search(text: str, days: int = 7, size: int = 20) -> Dict[str, Any]:
    """
    Build a quick search query for recent articles.
    
    Args:
        text: Search text
        days: Date range in days
        size: Number of results
        
    Returns:
        Elasticsearch query dict
    """
    return (SearchQueryBuilder()
        .text(text)
        .filter_date_range(days=days)
        .sort_by_relevance()
        .size(size)
        .build())
