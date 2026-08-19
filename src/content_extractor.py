"""
Content extraction utilities for scraping web pages.

This module provides utilities for extracting clean text content
from HTML pages, removing navigation, ads, and other non-content
elements.
"""

from typing import List, Optional

from bs4 import BeautifulSoup


class ContentExtractor:
    """
    Extracts main content from web pages.
    
    Uses a multi-strategy approach:
    1. Try common content container selectors
    2. Fall back to main body content
    3. Clean up by removing known non-content elements
    
    Class Attributes:
        CONTENT_SELECTORS: CSS selectors for common content containers.
        REMOVE_SELECTORS: CSS selectors for elements to remove.
    """
    
    # Selectors for finding main content (in priority order)
    CONTENT_SELECTORS: List[str] = [
        "article",
        '[itemprop="articleBody"]',
        '[role="article"]',
        ".post-content",
        ".entry-content",
        ".content-body",
        ".article-content",
        ".article-body",
        ".story-body",
        ".post-body",
        "#article-body",
        "#content",
        "main",
    ]
    
    # Selectors for elements to remove before extraction
    REMOVE_SELECTORS: List[str] = [
        "script",
        "style",
        "nav",
        "header",
        "footer",
        "aside",
        "noscript",
        "iframe",
        "form",
        ".social-share",
        ".share-buttons",
        ".related-articles",
        ".recommended",
        ".comments",
        ".comment-section",
        ".ad-slot",
        ".advertisement",
        ".promo",
        ".newsletter-signup",
        ".sidebar",
        ".breadcrumb",
        ".pagination",
        '[role="navigation"]',
        '[role="banner"]',
        '[role="complementary"]',
    ]
    
    @staticmethod
    def clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
        """
        Remove unwanted elements from BeautifulSoup object.
        
        Modifies the soup in-place by decomposing elements matching
        the REMOVE_SELECTORS.
        
        Args:
            soup: BeautifulSoup object to clean.
        
        Returns:
            The cleaned BeautifulSoup object (same reference).
        """
        for selector in ContentExtractor.REMOVE_SELECTORS:
            for element in soup.select(selector):
                element.decompose()
        return soup
    
    @staticmethod
    def find_content_container(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """
        Find the main content container in a page.
        
        Tries each content selector in priority order until one matches.
        
        Args:
            soup: BeautifulSoup object to search.
        
        Returns:
            BeautifulSoup element containing main content, or None.
        """
        for selector in ContentExtractor.CONTENT_SELECTORS:
            content = soup.select_one(selector)
            if content:
                return content
        return None
    
    @staticmethod
    def extract_text(soup: BeautifulSoup) -> str:
        """
        Extract main text content from a BeautifulSoup object.
        
        Cleans the HTML, finds the content container, and extracts
        clean text. Falls back to body content if no container found.
        
        Args:
            soup: BeautifulSoup object representing the HTML page.
        
        Returns:
            Extracted text content. Returns error message if extraction fails.
        """
        # Clean the soup first
        ContentExtractor.clean_soup(soup)
        
        # Try to find main content container
        content = ContentExtractor.find_content_container(soup)
        
        # Fallback to body if no specific content found
        if not content:
            content = soup.find("body")
        
        if not content:
            return "Content extraction failed."
        
        # Extract and clean text
        text = content.get_text(separator=" ", strip=True)
        
        # Basic text cleaning
        # Remove excessive whitespace
        import re
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    @staticmethod
    def extract_title(soup: BeautifulSoup) -> Optional[str]:
        """
        Extract the page title from HTML.
        
        Tries multiple methods in priority order:
        1. OpenGraph title
        2. H1 tag
        3. Title tag
        
        Args:
            soup: BeautifulSoup object to search.
        
        Returns:
            Page title string, or None if not found.
        """
        # Try OpenGraph title first
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()
        
        # Try first H1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        
        # Fall back to title tag
        title = soup.find("title")
        if title:
            return title.get_text(strip=True)
        
        return None
    
    @staticmethod
    def extract_meta_description(soup: BeautifulSoup) -> Optional[str]:
        """
        Extract meta description from HTML.
        
        Args:
            soup: BeautifulSoup object to search.
        
        Returns:
            Meta description string, or None if not found.
        """
        # Try OpenGraph description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return og_desc["content"].strip()
        
        # Try standard meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return meta_desc["content"].strip()
        
        return None
    
    @staticmethod
    def extract_author(soup: BeautifulSoup) -> Optional[str]:
        """
        Extract author name from HTML.
        
        Args:
            soup: BeautifulSoup object to search.
        
        Returns:
            Author name string, or None if not found.
        """
        # Try author meta tag
        author_meta = soup.find("meta", attrs={"name": "author"})
        if author_meta and author_meta.get("content"):
            return author_meta["content"].strip()
        
        # Try schema.org author
        author_elem = soup.find(itemprop="author")
        if author_elem:
            return author_elem.get_text(strip=True)
        
        # Try common author classes
        for selector in [".author", ".byline", ".post-author"]:
            author = soup.select_one(selector)
            if author:
                return author.get_text(strip=True)
        
        return None
    
    @staticmethod
    def extract_publish_date(soup: BeautifulSoup) -> Optional[str]:
        """
        Extract publication date from HTML.
        
        Args:
            soup: BeautifulSoup object to search.
        
        Returns:
            Date string (format varies), or None if not found.
        """
        # Try article:published_time
        pub_time = soup.find("meta", property="article:published_time")
        if pub_time and pub_time.get("content"):
            return pub_time["content"]
        
        # Try schema.org datePublished
        date_elem = soup.find(itemprop="datePublished")
        if date_elem:
            return date_elem.get("content") or date_elem.get_text(strip=True)
        
        # Try time element
        time_elem = soup.find("time")
        if time_elem and time_elem.get("datetime"):
            return time_elem["datetime"]
        
        return None