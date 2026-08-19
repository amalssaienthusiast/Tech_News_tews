"""
Intelligent Query Engine for understanding user intent.

This module provides advanced query analysis capabilities:
- Intent classification (search, analyze, discover, reject)
- Tech relevance scoring using ML and keyword matching
- Query expansion with synonyms and related terms
- Strict non-tech content rejection
"""

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

# Import from parent package
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.types import QueryIntent, QueryResult, TechScore
from src.core.exceptions import NonTechQueryError, InvalidQueryError
from src.data_structures.trie import TechKeywordMatcher


class QueryType(Enum):
    """Type of query detected."""
    KEYWORD_SEARCH = auto()      # General tech keyword search
    URL_ANALYSIS = auto()        # Analyze specific URL
    SOURCE_DISCOVERY = auto()    # Find new sources
    TRENDING = auto()            # Get trending topics
    HELP = auto()                # Help/usage query
    UNKNOWN = auto()             # Cannot classify


@dataclass
class ExpandedQuery:
    """
    Query with expanded terms and metadata.
    
    Attributes:
        original: Original query string
        normalized: Cleaned and normalized query
        terms: Individual terms after tokenization
        expanded_terms: Additional related terms
        detected_entities: Named entities detected
        url: Extracted URL if any
    """
    original: str
    normalized: str
    terms: Tuple[str, ...]
    expanded_terms: Tuple[str, ...] = field(default_factory=tuple)
    detected_entities: Dict[str, List[str]] = field(default_factory=dict)
    url: Optional[str] = None


class QueryEngine:
    """
    Intelligent query analysis engine.
    
    Provides comprehensive query understanding including intent
    classification, tech relevance scoring, and expansion.
    Uses the Trie-based TechKeywordMatcher for fast keyword detection.
    
    Example:
        engine = QueryEngine()
        
        # Valid tech query
        result = engine.analyze("latest developments in artificial intelligence")
        print(result.is_accepted)  # True
        print(result.tech_score.score)  # 0.95
        
        # Non-tech query (rejected)
        result = engine.analyze("best pizza places near me")
        print(result.is_accepted)  # False
        print(result.rejection_reason)  # "Not tech-related"
    
    Attributes:
        tech_threshold: Minimum tech score to accept query
        min_query_length: Minimum query length
        max_query_length: Maximum query length
    """
    
    # Query intent patterns
    URL_PATTERN = re.compile(
        r'https?://[^\s<>"{}|\\^`\[\]]+',
        re.IGNORECASE
    )
    
    DISCOVERY_PATTERNS = [
        r'\b(find|discover|search for|look for)\s+(new\s+)?(sources?|sites?|websites?)\b',
        r'\b(new|more)\s+(tech\s+)?(news\s+)?sources?\b',
    ]
    
    TRENDING_PATTERNS = [
        r'\b(trending|popular|hot|top)\s+(topics?|news|stories)\b',
        r'\bwhat\'?s?\s+(new|happening|trending)\b',
    ]
    
    HELP_PATTERNS = [
        r'\b(help|how\s+to|usage|commands?)\b',
        r'\bwhat\s+can\s+you\s+do\b',
    ]
    
    # Non-tech indicators (strong negative signals)
    NON_TECH_INDICATORS = {
        "recipe", "recipes", "cooking", "baking", "food",
        "weather", "sports", "game score", "movie", "movies",
        "restaurant", "hotels", "travel", "vacation", "flight",
        "celebrity", "gossip", "fashion", "makeup", "beauty",
        "dating", "relationship", "horoscope", "astrology",
        "lottery", "gambling", "casino", "betting",
        "diet", "weight loss", "exercise routine", "workout",
        "real estate", "mortgage", "property", "house hunting",
        "pets", "dogs", "cats", "animals",
        "gardening", "plants", "flowers",
        "music lyrics", "song lyrics",
    }
    
    # Tech domain synonyms for query expansion
    TECH_SYNONYMS: Dict[str, List[str]] = {
        "ai": ["artificial intelligence", "machine learning", "deep learning"],
        "ml": ["machine learning", "ai", "neural networks"],
        "llm": ["large language model", "gpt", "chatgpt", "language model"],
        "programming": ["coding", "software development", "development"],
        "cybersecurity": ["security", "infosec", "cyber security", "hacking"],
        "cloud": ["cloud computing", "aws", "azure", "gcp"],
        "blockchain": ["crypto", "web3", "decentralized"],
        "vr": ["virtual reality", "metaverse"],
        "ar": ["augmented reality", "mixed reality"],
        "iot": ["internet of things", "smart devices", "connected devices"],
        "api": ["apis", "rest api", "graphql", "web services"],
        "devops": ["ci/cd", "deployment", "infrastructure"],
    }
    
    def __init__(
        self,
        tech_threshold: float = 0.1,  # Lowered from 0.3 for better acceptance
        min_query_length: int = 2,
        max_query_length: int = 500
    ) -> None:
        """
        Initialize the query engine.
        
        Args:
            tech_threshold: Minimum tech score to accept (0.0 to 1.0)
            min_query_length: Minimum query length in characters
            max_query_length: Maximum query length in characters
        """
        self.tech_threshold = tech_threshold
        self.min_query_length = min_query_length
        self.max_query_length = max_query_length
        
        # Initialize keyword matcher
        self._keyword_matcher = TechKeywordMatcher()
        
        # Compile patterns
        self._discovery_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.DISCOVERY_PATTERNS
        ]
        self._trending_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.TRENDING_PATTERNS
        ]
        self._help_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.HELP_PATTERNS
        ]
    
    def analyze(self, query: str) -> QueryResult:
        """
        Analyze a query and determine intent and tech relevance.
        
        This is the main entry point for query analysis. Returns a
        QueryResult with intent classification and tech scoring.
        
        Args:
            query: User query string
        
        Returns:
            QueryResult with analysis results
        
        Raises:
            InvalidQueryError: If query is malformed
            NonTechQueryError: If query is not tech-related
        """
        # Validate query
        self._validate_query(query)
        
        # Normalize and expand query
        expanded = self._expand_query(query)
        
        # Check for URL (special handling)
        if expanded.url:
            return self._handle_url_query(expanded)
        
        # Detect query type
        query_type = self._detect_query_type(expanded)
        
        # Handle special query types
        if query_type == QueryType.HELP:
            return QueryResult(
                original_query=query,
                intent=QueryIntent.SEARCH,  # Treat as valid
                tech_score=TechScore(score=1.0, confidence=1.0),
                expanded_terms=tuple(),
            )
        
        if query_type == QueryType.TRENDING:
            return QueryResult(
                original_query=query,
                intent=QueryIntent.TRENDING,
                tech_score=TechScore(score=1.0, confidence=0.9),
                expanded_terms=tuple(),
            )
        
        if query_type == QueryType.SOURCE_DISCOVERY:
            return QueryResult(
                original_query=query,
                intent=QueryIntent.DISCOVER,
                tech_score=TechScore(score=1.0, confidence=0.9),
                expanded_terms=tuple(),
            )
        
        # Calculate tech relevance score
        tech_score = self._calculate_tech_score(expanded)
        
        # Check for explicit non-tech content FIRST
        if self._is_non_tech(expanded):
            return QueryResult(
                original_query=query,
                intent=QueryIntent.REJECTED,
                tech_score=tech_score,
                rejection_reason=(
                    "This query appears to be about non-tech topics. "
                    "Please ask about technology, software, AI, programming, "
                    "or other tech-related subjects."
                ),
            )
        
        # AUTO-ACCEPT: If query contains common tech words, accept it
        common_tech_words = {
            'technology', 'tech', 'software', 'hardware', 'computer', 'digital',
            'internet', 'web', 'app', 'application', 'programming', 'developer',
            'ai', 'ml', 'data', 'cyber', 'network', 'server', 'cloud', 'code',
            'coding', 'startup', 'innovation', 'gadget', 'device', 'platform',
            'automation', 'robot', 'algorithm', 'database', 'api', 'framework',
            'news', 'latest', 'new', 'update', 'release', 'launch', 'announce',
        }
        query_words = set(expanded.normalized.split())
        if query_words & common_tech_words:
            return QueryResult(
                original_query=query,
                intent=QueryIntent.SEARCH,
                tech_score=TechScore(score=max(0.5, tech_score.score), confidence=0.7),
                expanded_terms=expanded.expanded_terms,
            )
        
        # Check threshold only if no tech words detected
        if tech_score.score < self.tech_threshold:
            return QueryResult(
                original_query=query,
                intent=QueryIntent.REJECTED,
                tech_score=tech_score,
                rejection_reason=(
                    f"Query has low tech relevance (score: {tech_score.score:.2f}). "
                    "Please make your query more specific to technology topics."
                ),
            )
        
        # Accepted query
        return QueryResult(
            original_query=query,
            intent=QueryIntent.SEARCH,
            tech_score=tech_score,
            expanded_terms=expanded.expanded_terms,
        )
    
    def analyze_strict(self, query: str) -> QueryResult:
        """
        Analyze query with strict tech validation.
        
        Raises NonTechQueryError if query is rejected, allowing
        calling code to handle the exception.
        
        Args:
            query: User query string
        
        Returns:
            QueryResult for accepted queries
        
        Raises:
            NonTechQueryError: If query is not tech-related
        """
        result = self.analyze(query)
        
        if not result.is_accepted:
            raise NonTechQueryError(
                query=query,
                tech_score=result.tech_score.score,
                threshold=self.tech_threshold
            )
        
        return result
    
    def _validate_query(self, query: str) -> None:
        """Validate query format and length."""
        if not query:
            raise InvalidQueryError("Query cannot be empty")
        
        query = query.strip()
        
        if len(query) < self.min_query_length:
            raise InvalidQueryError(
                f"Query too short (minimum {self.min_query_length} characters)",
                query=query
            )
        
        if len(query) > self.max_query_length:
            raise InvalidQueryError(
                f"Query too long (maximum {self.max_query_length} characters)",
                query=query
            )
    
    def _expand_query(self, query: str) -> ExpandedQuery:
        """
        Expand and normalize the query.
        
        Performs:
        - Normalization (lowercase, trim)
        - URL extraction
        - Tokenization
        - Synonym expansion
        """
        original = query
        normalized = query.lower().strip()
        
        # Extract URL if present
        url_match = self.URL_PATTERN.search(query)
        url = url_match.group(0) if url_match else None
        
        # Remove URL from query for tokenization
        if url:
            normalized = self.URL_PATTERN.sub('', normalized).strip()
        
        # Tokenize
        terms = tuple(
            term for term in re.split(r'\s+', normalized)
            if term and len(term) > 1
        )
        
        # Expand with synonyms
        expanded_terms: Set[str] = set()
        for term in terms:
            if term in self.TECH_SYNONYMS:
                expanded_terms.update(self.TECH_SYNONYMS[term])
        
        return ExpandedQuery(
            original=original,
            normalized=normalized,
            terms=terms,
            expanded_terms=tuple(expanded_terms),
            url=url,
        )
    
    def _detect_query_type(self, expanded: ExpandedQuery) -> QueryType:
        """Detect the type of query."""
        text = expanded.normalized
        
        # Check for help queries
        for pattern in self._help_patterns:
            if pattern.search(text):
                return QueryType.HELP
        
        # Check for trending queries
        for pattern in self._trending_patterns:
            if pattern.search(text):
                return QueryType.TRENDING
        
        # Check for discovery queries
        for pattern in self._discovery_patterns:
            if pattern.search(text):
                return QueryType.SOURCE_DISCOVERY
        
        return QueryType.KEYWORD_SEARCH
    
    def _handle_url_query(self, expanded: ExpandedQuery) -> QueryResult:
        """Handle queries containing URLs."""
        url = expanded.url
        
        # Validate URL
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return QueryResult(
                    original_query=expanded.original,
                    intent=QueryIntent.REJECTED,
                    tech_score=TechScore(score=0.0, confidence=1.0),
                    rejection_reason=f"Invalid URL format: {url}",
                )
        except Exception:
            return QueryResult(
                original_query=expanded.original,
                intent=QueryIntent.REJECTED,
                tech_score=TechScore(score=0.0, confidence=1.0),
                rejection_reason=f"Could not parse URL: {url}",
            )
        
        return QueryResult(
            original_query=expanded.original,
            intent=QueryIntent.ANALYZE_URL,
            tech_score=TechScore(score=1.0, confidence=0.8),
            expanded_terms=tuple(),
        )
    
    def _calculate_tech_score(self, expanded: ExpandedQuery) -> TechScore:
        """
        Calculate tech relevance score using keyword matching.
        
        Uses the TechKeywordMatcher for efficient matching and
        applies scoring based on:
        - Number of tech keywords
        - Keyword weights
        - Query context
        """
        # Combine original query and expanded terms
        full_text = expanded.normalized
        if expanded.expanded_terms:
            full_text += " " + " ".join(expanded.expanded_terms)
        
        # Use keyword matcher
        score, matched_keywords = self._keyword_matcher.calculate_tech_score(full_text)
        
        # Determine categories from matched keywords
        categories = self._categorize_keywords(matched_keywords)
        
        # Confidence based on number of matches
        confidence = min(1.0, len(matched_keywords) * 0.2 + 0.3)
        
        return TechScore(
            score=score,
            confidence=confidence,
            matched_keywords=tuple(matched_keywords),
            categories=tuple(categories),
        )
    
    def _categorize_keywords(self, keywords: List[str]) -> List[str]:
        """Categorize matched keywords into tech domains."""
        categories: Set[str] = set()
        
        category_map = {
            "AI/ML": {"ai", "artificial intelligence", "machine learning", "deep learning", "neural network", "llm", "gpt"},
            "Programming": {"programming", "coding", "software", "developer", "python", "javascript", "api"},
            "Cloud": {"cloud", "aws", "azure", "kubernetes", "docker", "serverless"},
            "Security": {"cybersecurity", "security", "encryption", "hacking", "malware"},
            "Blockchain": {"blockchain", "cryptocurrency", "bitcoin", "ethereum", "web3"},
            "Hardware": {"semiconductor", "chip", "gpu", "processor", "nvidia"},
            "Emerging Tech": {"vr", "ar", "virtual reality", "augmented reality", "iot", "advanced computing"},
        }
        
        keyword_set = set(k.lower() for k in keywords)
        
        for category, category_keywords in category_map.items():
            if keyword_set & category_keywords:
                categories.add(category)
        
        return list(categories)
    
    def _is_non_tech(self, expanded: ExpandedQuery) -> bool:
        """
        Check if query contains strong non-tech indicators.
        
        Returns True if query is definitely not tech-related.
        """
        text = expanded.normalized
        
        for indicator in self.NON_TECH_INDICATORS:
            if indicator in text:
                return True
        
        return False
    
    def get_search_terms(self, result: QueryResult) -> List[str]:
        """
        Get optimized search terms from query result.
        
        Returns a list of terms suitable for web search,
        combining original terms and expansions.
        """
        if not result.is_accepted:
            return []
        
        terms = list(result.tech_score.matched_keywords)
        
        # Add expansion terms
        terms.extend(result.expanded_terms)
        
        # Deduplicate while preserving order
        seen = set()
        unique_terms = []
        for term in terms:
            if term.lower() not in seen:
                seen.add(term.lower())
                unique_terms.append(term)
        
        return unique_terms[:10]  # Limit to 10 terms
    
    def suggest_tech_queries(self, failed_query: str) -> List[str]:
        """
        Suggest related tech queries when a query is rejected.
        
        Args:
            failed_query: The rejected query
        
        Returns:
            List of suggested tech-related queries
        """
        suggestions = [
            "latest artificial intelligence news",
            "new programming frameworks",
            "cybersecurity trends",
            "cloud computing updates",
            "startup funding news",
            "tech industry analysis",
        ]
        
        # Try to make contextual suggestions
        query_lower = failed_query.lower()
        
        if any(word in query_lower for word in ["app", "application", "software"]):
            suggestions.insert(0, "new software releases and updates")
        
        if any(word in query_lower for word in ["company", "business"]):
            suggestions.insert(0, "tech company news and acquisitions")
        
        return suggestions[:5]
