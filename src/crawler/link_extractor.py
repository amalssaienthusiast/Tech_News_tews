"""
Link Extractor for Web Crawler

Extracts and categorizes links from web pages with intelligent filtering.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


@dataclass
class ExtractedLink:
    """Represents an extracted link with metadata."""
    url: str
    text: str = ""
    is_internal: bool = True
    is_article: bool = False
    depth_found: int = 0
    parent_url: str = ""
    score: float = 0.0  # Relevance score


class LinkExtractor:
    """
    Intelligent link extractor with article detection and filtering.
    
    Features:
    - Article URL pattern detection
    - Internal/external link classification
    - Relevance scoring based on anchor text
    - Duplicate and irrelevant link filtering
    """
    
    # URL patterns that typically indicate article pages
    ARTICLE_PATTERNS = [
        r'/\d{4}/\d{2}/\d{2}/',        # /2024/01/15/
        r'/article/',
        r'/news/',
        r'/story/',
        r'/post/',
        r'/blog/',
        r'/p/',                          # Medium, Substack
        r'/\w+-\w+-\w+',                 # slug-style URLs
        r'-\d{5,}$',                     # ID at end
        r'/\d{5,}/',                     # Numeric ID in path
    ]
    
    # Patterns to skip
    SKIP_PATTERNS = [
        r'/tag/',
        r'/category/',
        r'/author/',
        r'/search',
        r'/login',
        r'/signup',
        r'/subscribe',
        r'/about',
        r'/contact',
        r'/privacy',
        r'/terms',
        r'/careers',
        r'\?utm_',
        r'#',
        r'/cdn-cgi/',
        r'javascript:',
        r'mailto:',
    ]
    
    # Tech keywords for relevance scoring
    TECH_KEYWORDS = [
        'ai', 'artificial-intelligence', 'machine-learning', 'ml',
        'startup', 'funding', 'acquisition', 'tech', 'technology',
        'cloud', 'aws', 'azure', 'google', 'microsoft', 'apple',
        'openai', 'chatgpt', 'gpt', 'gemini', 'llm', 'neural',
        'security', 'cyber', 'privacy', 'data', 'api',
        'software', 'developer', 'coding', 'programming',
        'crypto', 'blockchain', 'fintech',
    ]
    
    def __init__(self, base_domain: str = ""):
        """
        Initialize link extractor.
        
        Args:
            base_domain: Domain to consider as internal (e.g., 'techcrunch.com')
        """
        self.base_domain = base_domain.lower()
        self._seen_urls: Set[str] = set()
    
    def extract_links(
        self,
        html: str,
        page_url: str,
        depth: int = 0,
        max_links: int = 100
    ) -> List[ExtractedLink]:
        """
        Extract links from HTML content.
        
        Args:
            html: HTML content to parse
            page_url: URL of the page being parsed
            depth: Current crawl depth
            max_links: Maximum links to return
            
        Returns:
            List of ExtractedLink objects, sorted by relevance
        """
        from bs4 import BeautifulSoup
        
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        links: List[ExtractedLink] = []
        
        parsed_base = urlparse(page_url)
        base_domain = parsed_base.netloc.lower()
        
        if not self.base_domain:
            self.base_domain = base_domain
        
        for anchor in soup.find_all('a', href=True):
            href = anchor.get('href', '').strip()
            text = anchor.get_text(strip=True)[:200]
            
            if not href or self._should_skip(href):
                continue
            
            # Make URL absolute
            full_url = urljoin(page_url, href)
            parsed = urlparse(full_url)
            
            # Skip non-HTTP
            if parsed.scheme not in ('http', 'https'):
                continue
            
            # Normalize URL (remove fragment, trailing slash)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            clean_url = clean_url.rstrip('/')
            
            # Deduplicate
            if clean_url in self._seen_urls:
                continue
            self._seen_urls.add(clean_url)
            
            # Classify link
            is_internal = parsed.netloc.lower() == self.base_domain
            is_article = self._is_article_url(parsed.path, text)
            score = self._calculate_relevance(parsed.path, text)
            
            links.append(ExtractedLink(
                url=clean_url,
                text=text,
                is_internal=is_internal,
                is_article=is_article,
                depth_found=depth,
                parent_url=page_url,
                score=score
            ))
        
        # Sort by relevance score (articles first, then by score)
        links.sort(key=lambda x: (not x.is_article, -x.score))
        
        return links[:max_links]
    
    def _should_skip(self, url: str) -> bool:
        """Check if URL should be skipped."""
        url_lower = url.lower()
        for pattern in self.SKIP_PATTERNS:
            if re.search(pattern, url_lower):
                return True
        return False
    
    def _is_article_url(self, path: str, anchor_text: str = "") -> bool:
        """Determine if URL likely points to an article."""
        path_lower = path.lower()
        
        # Check path patterns
        for pattern in self.ARTICLE_PATTERNS:
            if re.search(pattern, path_lower):
                return True
        
        # Check if anchor text is substantial (article titles are usually 5+ words)
        if anchor_text and len(anchor_text.split()) >= 5:
            return True
        
        return False
    
    def _calculate_relevance(self, path: str, anchor_text: str) -> float:
        """Calculate relevance score for a link (0-1)."""
        score = 0.0
        combined = (path + ' ' + anchor_text).lower()
        
        # Keyword matches
        keywords_found = sum(1 for kw in self.TECH_KEYWORDS if kw in combined)
        score += min(keywords_found * 0.1, 0.5)
        
        # Article pattern bonus
        if self._is_article_url(path, anchor_text):
            score += 0.3
        
        # Anchor text length bonus (longer = more likely article)
        text_words = len(anchor_text.split()) if anchor_text else 0
        score += min(text_words * 0.02, 0.2)
        
        return min(score, 1.0)
    
    def clear_seen(self):
        """Clear seen URLs cache."""
        self._seen_urls.clear()
    
    def filter_article_links(
        self,
        links: List[ExtractedLink],
        min_score: float = 0.2
    ) -> List[ExtractedLink]:
        """Filter to only article links above minimum score."""
        return [
            link for link in links
            if link.is_article and link.score >= min_score
        ]
