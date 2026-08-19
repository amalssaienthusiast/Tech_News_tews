
import re
from bs4 import BeautifulSoup
import json
from typing import Dict, Optional, List
import logging

class MediumContentExtractor:
    """Specialized extractor for Medium.com articles"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.patterns = {
            'content': [
                r'<article[^>]*>.*?</article>',
                r'<div[^>]*class="[^"]*postArticle[^"]*"[^>]*>.*?</div>',
                r'<div[^>]*data-testid="post-content"[^>]*>.*?</div>',
                r'<section[^>]*data-field="body"[^>]*>.*?</section>',
            ],
            'title': [
                r'<h1[^>]*>.*?</h1>',
                r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"',
                r'<title>([^<]*)</title>'
            ],
            'author': [
                r'<meta[^>]*property="article:author"[^>]*content="([^"]*)"',
                r'<a[^>]*rel="author"[^>]*>([^<]*)</a>',
                r'<div[^>]*class="[^"]*author[^"]*"[^>]*>.*?</div>',
            ],
            'date': [
                r'<meta[^>]*property="article:published_time"[^>]*content="([^"]*)"',
                r'<time[^>]*datetime="([^"]*)"[^>]*>',
                r'<div[^>]*class="[^"]*timestamp[^"]*"[^>]*>.*?</div>'
            ]
        }
    
    def extract_clean_content(self, html: str, url: str) -> Dict:
        """Extract clean content from Medium HTML"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Method 1: Extract from JSON-LD structured data
            content = self._extract_from_jsonld(soup)
            if content and len(content.get('content', '')) > 500:
                # Only trust JSON-LD if it has substantial content
                return content
            elif content:
                self.logger.warning(f"JSON-LD content too short ({len(content.get('content', ''))} chars), falling back to scraping")
            
            # Method 2: Find article content by common Medium classes
            content = self._extract_by_medium_classes(soup)
            if content:
                return content
            
            # Method 3: Try to find the main article section
            content = self._extract_by_section_analysis(soup)
            if content:
                return content
            
            # Method 4: Fallback to generic extraction
            content = self._extract_generic(soup)
            
            return {
                'url': url,
                'title': content.get('title', ''),
                'author': content.get('author', ''),
                'published_date': content.get('date', ''),
                'content': content.get('content', ''),
                'word_count': len(content.get('content', '').split()),
                'extraction_method': content.get('method', 'generic'),
                'success': True
            }
            
        except Exception as e:
            self.logger.error(f"Error extracting Medium content: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _extract_from_jsonld(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Extract content from JSON-LD structured data"""
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    return {
                        'title': data.get('headline', ''),
                        'author': data.get('author', {}).get('name', ''),
                        'published_date': data.get('datePublished', ''),
                        'content': data.get('articleBody', ''),
                        'method': 'jsonld',
                        'success': True
                    }
                elif isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Article':
                            return {
                                'title': item.get('headline', ''),
                                'author': item.get('author', {}).get('name', ''),
                                'published_date': item.get('datePublished', ''),
                                'content': item.get('articleBody', ''),
                                'method': 'jsonld',
                                'success': True
                            }
            except Exception as e:
                self.logger.debug(f"_extract_from_jsonld: suppressed {type(e).__name__}: {e}")
                continue
        return None
    
    def _extract_by_medium_classes(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Extract content using known Medium CSS classes"""
        # Find title
        title_elem = None
        for class_name in ['pw-post-title', 'postArticle-title', 'section-title']:
            title_elem = soup.find(class_=class_name)
            if title_elem:
                break
        
        if not title_elem:
             title_elem = self._extract_title(soup)
        
        # Method A: Aggregate all individual paragraphs (Most reliable for Medium)
        # Medium uses 'pw-post-body-paragraph' for actual article text
        paragraphs = soup.find_all(class_='pw-post-body-paragraph')
        if paragraphs and len(paragraphs) > 3:
            content_text = '\n\n'.join([p.get_text(strip=True) for p in paragraphs])
            return {
                'title': title_elem.get_text(strip=True) if hasattr(title_elem, 'get_text') else str(title_elem),
                'author': self._extract_author(soup),
                'published_date': self._extract_date(soup),
                'content': content_text,
                'method': 'medium_paragraphs',
                'success': True
            }

        # Method B: Main content containers
        content_elem = None
        # Prioritize 'article' tag if it has substantial content
        article_tag = soup.find('article')
        if article_tag and len(article_tag.get_text(strip=True)) > 500:
             content_elem = article_tag
        
        if not content_elem:
            for class_name in ['postArticle-content', 'section-content', 'section-inner', 'article-body']:
                # Find all, pick largest
                candidates = soup.find_all(class_=class_name)
                if candidates:
                    content_elem = max(candidates, key=lambda c: len(c.get_text(strip=True)))
                    break
        
        if content_elem:
            # Remove unwanted elements
            for unwanted in content_elem.find_all(['script', 'style', 'nav', 'footer', 
                                                   'aside', 'form', 'button', 'input']):
                unwanted.decompose()
            
            # Extract text
            content_text = content_elem.get_text(separator='\n', strip=True)
            
            return {
                'title': title_elem.get_text(strip=True) if hasattr(title_elem, 'get_text') else str(title_elem),
                'author': self._extract_author(soup),
                'published_date': self._extract_date(soup),
                'content': content_text,
                'method': 'medium_classes',
                'success': True
            }
        
        return None
    
    def _extract_by_section_analysis(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Analyze DOM structure to find main content"""
        # Find largest text block
        main_content = None
        max_text_length = 0
        
        # Look for article tags
        articles = soup.find_all('article')
        for article in articles:
            text = article.get_text(strip=True)
            if len(text) > max_text_length:
                max_text_length = len(text)
                main_content = article
        
        # Look for divs with substantial text
        if not main_content:
            divs = soup.find_all('div')
            for div in divs:
                # Skip navigation, headers, footers
                if div.find_parent(['nav', 'header', 'footer', 'aside']):
                    continue
                
                text = div.get_text(strip=True)
                if len(text) > 500 and len(text) > max_text_length:  # Substantial content
                    max_text_length = len(text)
                    main_content = div
        
        if main_content:
            # Clean up the content
            for unwanted in main_content.find_all(['script', 'style', 'nav', 'footer', 
                                                   'aside', 'form', 'button', 'input', 
                                                   'img', 'video', 'audio', 'iframe']):
                unwanted.decompose()
            
            content_text = main_content.get_text(separator='\n', strip=True)
            
            return {
                'title': self._extract_title(soup),
                'author': self._extract_author(soup),
                'published_date': self._extract_date(soup),
                'content': content_text,
                'method': 'section_analysis',
                'success': True
            }
        
        return None
    
    def _extract_generic(self, soup: BeautifulSoup) -> Dict:
        """Generic extraction as fallback"""
        # Extract title
        title = self._extract_title(soup)
        
        # Extract author
        author = self._extract_author(soup)
        
        # Extract date
        date = self._extract_date(soup)
        
        # Try to find main content using heuristics
        # 1. Look for largest paragraph block
        paragraphs = soup.find_all('p')
        content_paragraphs = []
        
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) > 100:  # Filter out short paragraphs
                content_paragraphs.append(text)
        
        content = '\n'.join(content_paragraphs)
        
        # 2. If no substantial paragraphs, extract from body
        if len(content) < 500:
            body = soup.find('body')
            if body:
                # Remove navigation, headers, footers
                for elem in body.find_all(['nav', 'header', 'footer', 'aside', 
                                          'script', 'style']):
                    elem.decompose()
                content = body.get_text(separator='\n', strip=True)
        
        return {
            'title': title,
            'author': author,
            'date': date,
            'content': content,
            'method': 'generic',
            'success': True
        }
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title"""
        # Try meta tags first
        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            return meta_title['content']
        
        # Try page title
        page_title = soup.find('title')
        if page_title:
            title_text = page_title.get_text(strip=True)
            # Remove "| Medium" suffix
            if '|' in title_text:
                title_text = title_text.split('|')[0].strip()
            return title_text
        
        # Try h1 tags
        h1 = soup.find('h1')
        if h1:
            return h1.get_text(strip=True)
        
        return ''
    
    def _extract_author(self, soup: BeautifulSoup) -> str:
        """Extract author name"""
        # Meta tag
        meta_author = soup.find('meta', property='article:author')
        if meta_author and meta_author.get('content'):
            return meta_author['content']
        
        # Look for author links
        author_link = soup.find('a', rel='author')
        if author_link:
            return author_link.get_text(strip=True)
        
        # Look for author divs
        for class_name in ['author-name', 'byline', 'post-author']:
            author_elem = soup.find(class_=class_name)
            if author_elem:
                return author_elem.get_text(strip=True)
        
        return ''
    
    def _extract_date(self, soup: BeautifulSoup) -> str:
        """Extract publication date"""
        # Meta tag
        meta_date = soup.find('meta', property='article:published_time')
        if meta_date and meta_date.get('content'):
            return meta_date['content']
        
        # Time element
        time_elem = soup.find('time')
        if time_elem and time_elem.get('datetime'):
            return time_elem['datetime']
        
        return ''
    
    def clean_content(self, content: str) -> str:
        """Clean extracted content"""
        # Remove excessive whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # Remove common Medium patterns
        patterns_to_remove = [
            r'Sign up for .*? newsletter',
            r'Subscribe to .*? get',
            r'Get .*? free',
            r'Read more from .*? on Medium',
            r'Follow .*? for more',
            r'Originally published at .*? on',
            r'\.{3,}',  # Ellipsis
        ]
        
        for pattern in patterns_to_remove:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        return content.strip()
