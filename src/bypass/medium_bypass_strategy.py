
from typing import Optional, Dict
import logging
try:
    from playwright.sync_api import Page, BrowserContext
except ImportError:
    Page = None
    BrowserContext = None
import time
import re

class MediumBypassStrategy:
    """Specialized bypass strategy for Medium.com"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.medium_eraser_script = """
        // Medium-specific DOM manipulation
        (function() {
            // Remove paywall overlays
            document.querySelectorAll('[class*="metered"], [class*="paywall"], [class*="overlay"]').forEach(el => el.remove());
            
            // Unlock content blocks
            document.querySelectorAll('article, div').forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.maxHeight === 'none' || style.overflow === 'hidden') {
                    el.style.maxHeight = 'none';
                    el.style.overflow = 'visible';
                }
            });
            
            // Remove blur effects
            document.querySelectorAll('*').forEach(el => {
                if (el.style.filter && el.style.filter.includes('blur')) {
                    el.style.filter = 'none';
                }
            });
            
            // Remove "Sign in to read" buttons
            document.querySelectorAll('button, a').forEach(el => {
                if (el.textContent && el.textContent.includes('Sign in') && el.textContent.includes('read')) {
                    el.remove();
                }
            });
            
            // Unlock scroll
            document.body.style.overflow = 'auto';
            document.documentElement.style.overflow = 'auto';
        })();
        """
    
    def execute(self, page: Page, url: str) -> Optional[str]:
        """Execute Medium-specific bypass"""
        try:
            # Navigate with stealth
            page.goto(url, wait_until='networkidle')
            
            # Wait for content to load
            page.wait_for_timeout(2000)
            
            # Inject Medium eraser script
            page.evaluate(self.medium_eraser_script)
            
            # Additional Medium-specific manipulation
            self._medium_specific_cleanup(page)
            
            # Extract content
            content = self._extract_medium_content(page)
            
            return content
            
        except Exception as e:
            self.logger.error(f"Medium bypass failed: {str(e)}")
            return None
    
    def _medium_specific_cleanup(self, page: Page):
        """Medium-specific cleanup"""
        # Remove newsletter signups
        page.evaluate("""
            document.querySelectorAll('[class*="newsletter"], [class*="subscribe"], [class*="cta"]').forEach(el => el.remove());
        """)
        
        # Unlock premium content
        page.evaluate("""
            // Remove premium content blockers
            const blockers = document.querySelectorAll('div[class*="locked"], div[class*="premium"], div[class*="member"]');
            blockers.forEach(blocker => {
                const parent = blocker.parentElement;
                if (parent) {
                    const content = blocker.nextElementSibling || blocker.innerHTML;
                    parent.innerHTML = content;
                }
            });
        """)
        
        # Remove "Read more" truncation
        page.evaluate("""
            document.querySelectorAll('[class*="truncate"], [class*="read-more"]').forEach(el => {
                el.style.maxHeight = 'none';
                el.style.overflow = 'visible';
            });
        """)
    
    def _extract_medium_content(self, page: Page) -> str:
        """Extract content from Medium page"""
        # Try multiple extraction methods
        extraction_scripts = [
            # Method 1: Extract from article tag
            """
            const article = document.querySelector('article');
            return article ? article.innerText : '';
            """,
            
            # Method 2: Extract from post content
            """
            const content = document.querySelector('[class*="postArticle"], [class*="post-content"]');
            return content ? content.innerText : '';
            """,
            
            # Method 3: Extract all paragraphs
            """
            const paragraphs = document.querySelectorAll('article p, .postArticle p, .section-content p');
            return Array.from(paragraphs).map(p => p.innerText).join('\\n');
            """,
            
            # Method 4: Full page text (fallback)
            """
            const body = document.querySelector('body');
            // Remove navigation, headers, footers
            const unwanted = body.querySelectorAll('nav, header, footer, aside, script, style');
            unwanted.forEach(el => el.remove());
            return body.innerText;
            """
        ]
        
        for script in extraction_scripts:
            content = page.evaluate(script)
            if content and len(content.strip()) > 500:  # Substantial content
                return content
        
        # Fallback: Get entire page HTML
        return page.content()
