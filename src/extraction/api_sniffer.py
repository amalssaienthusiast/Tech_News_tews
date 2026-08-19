import json
import re
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class ApiSniffer:
    """
    Analyzes network traffic to identify and extract content from API endpoints.
    Can be used standalone or integrated with StealthBrowserBypass.
    """
    
    # Common API patterns that return article content
    CONTENT_API_PATTERNS = [
        r'/api/v\d+/articles?/[\w-]+',
        r'/api/content/[\w-]+',
        r'/wp-json/wp/v\d+/posts/\d+',
        r'/graphql',
        r'/api/posts?/\d+',
        r'/data/article/[\w-]+',
        r'/_next/data/[\w-]+/[\w-]+.json'
    ]
    
    # JSON paths where content is typically stored
    CONTENT_JSON_PATHS = [
        ['data', 'content'],
        ['data', 'body'],
        ['data', 'article', 'content'],
        ['post', 'content'],
        ['article', 'content'],
        ['content', 'rendered'],
        ['content'],
        ['data', 'post', 'content']
    ]

    def __init__(self, captured_responses: Dict[str, Any] = None):
        self.captured_responses = captured_responses or {}

    def analyze_responses(self, responses: Dict[str, Any]) -> Optional[str]:
        """
        Analyze captured API responses to find full article content
        """
        logger.info(f"Analyzing {len(responses)} API responses for content...")
        
        for url, data in responses.items():
            if not isinstance(data, (dict, list)):
                continue
                
            # Check if URL matches content API patterns
            if any(re.search(pattern, url, re.I) for pattern in self.CONTENT_API_PATTERNS):
                logger.info(f"Potential content API found: {url}")
                
                # Try to extract content from JSON
                content = self._extract_from_json(data)
                if content and len(content) > 1000:  # Validate length
                    logger.info(f"Successfully extracted {len(content)} chars from API")
                    return content
        
        return None

    def _extract_from_json(self, data: Any, path: List[str] = None) -> Optional[str]:
        """Recursively search JSON for content fields"""
        
        if path is None:
            path = []
            
        # Try direct path matching
        for content_path in self.CONTENT_JSON_PATHS:
            try:
                temp = data
                for key in content_path:
                    temp = temp[key]
                if isinstance(temp, str) and len(temp) > 500:
                    logger.info(f"Found content at path: {content_path}")
                    return temp
            except (KeyError, TypeError):
                continue
        
        # Recursive search for large text fields
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and len(value) > 1000:
                    # Heuristic: check for HTML tags or article-like structure
                    if '<p>' in value or '>' in value:
                        logger.info(f"Found large text field: {key}")
                        return value
                elif isinstance(value, (dict, list)):
                    result = self._extract_from_json(value, path + [key])
                    if result:
                        return result
        
        elif isinstance(data, list):
            for i, item in enumerate(data):
                result = self._extract_from_json(item, path + [str(i)])
                if result:
                    return result
        
        return None

    def sniff_from_html(self, html: str) -> Optional[str]:
        """
        Extract API endpoints from HTML and simulate requests.
        Also parses intercepted responses injected by StealthBrowserBypass.
        """
        # 1. Parse injected captured responses (from StealthBrowserBypass)
        captured_match = re.search(r"<script id='__CAPTURED_API_RESPONSES__' type='application/json'>(.+?)</script>", html, re.S)
        if captured_match:
            try:
                captured_data = json.loads(captured_match.group(1))
                content = self.analyze_responses(captured_data)
                if content:
                    return content
            except Exception as e:
                logger.debug(f"Failed to parse captured API responses: {e}")

        # 2. Look for GraphQL endpoints
        graphql_match = re.search(r'window\.__APOLLO_STATE__\s*=\s*({.+?});', html, re.S)
        if graphql_match:
            try:
                data = json.loads(graphql_match.group(1))
                content = self._extract_from_json(data)
                if content:
                    logger.info("Extracted content from GraphQL state")
                    return content
            except Exception as e:
                logger.debug(f"sniff_from_html: suppressed {type(e).__name__}: {e}")
                pass
        
        # 3. Look for Next.js data
        nextjs_match = re.search(r'window\.__NEXT_DATA__\s*=\s*({.+?});', html, re.S)
        if nextjs_match:
            try:
                data = json.loads(nextjs_match.group(1))
                content = self._extract_from_json(data)
                if content:
                    logger.info("Extracted content from Next.js data")
                    return content
            except Exception as e:
                logger.debug(f"sniff_from_html: suppressed {type(e).__name__}: {e}")
                pass
        
        # 4. Look for JSON-LD structured data
        ld_json_matches = re.findall(r'<script type="application/ld\+json">(.+?)</script>', html, re.S)
        for match in ld_json_matches:
            try:
                data = json.loads(match)
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    if 'articleBody' in data:
                        logger.info("Extracted content from JSON-LD")
                        return data['articleBody']
            except Exception as e:
                logger.debug(f"sniff_from_html: suppressed {type(e).__name__}: {e}")
                continue
        
        return None
