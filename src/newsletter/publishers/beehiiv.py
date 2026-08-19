"""
Beehiiv API Integration for Newsletter Publishing

Enables direct publishing to Beehiiv newsletter platform.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class BeehiivPublisher:
    """
    Beehiiv API client for newsletter publishing.
    
    Features:
    - Create draft posts
    - Schedule sends
    - Get publication stats
    """
    
    BASE_URL = "https://api.beehiiv.com/v2"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        publication_id: Optional[str] = None
    ):
        """
        Initialize Beehiiv publisher.
        
        Args:
            api_key: Beehiiv API key
            publication_id: Publication ID
        """
        self.api_key = api_key or os.getenv("BEEHIIV_API_KEY", "")
        self.publication_id = publication_id or os.getenv("BEEHIIV_PUBLICATION_ID", "")
    
    @property
    def is_configured(self) -> bool:
        """Check if Beehiiv is properly configured."""
        return bool(self.api_key and self.publication_id)
    
    def _get_headers(self) -> Dict[str, str]:
        """Get API headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def create_draft(
        self,
        title: str,
        content_html: str,
        subtitle: str = "",
        authors: Optional[list] = None
    ) -> Optional[str]:
        """
        Create a draft post in Beehiiv.
        
        Args:
            title: Post title (subject line)
            content_html: HTML content
            subtitle: Optional subtitle
            authors: Optional author IDs
            
        Returns:
            Post ID if successful, None otherwise
        """
        if not self.is_configured:
            logger.warning("Beehiiv not configured")
            return None
        
        url = f"{self.BASE_URL}/publications/{self.publication_id}/posts"
        
        payload = {
            "title": title,
            "subtitle": subtitle,
            "content_html": content_html,
            "status": "draft"
        }
        
        if authors:
            payload["authors"] = authors
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._get_headers()
                ) as resp:
                    if resp.status == 201:
                        data = await resp.json()
                        post_id = data.get("data", {}).get("id")
                        logger.info(f"Beehiiv draft created: {post_id}")
                        return post_id
                    else:
                        error = await resp.text()
                        logger.error(f"Beehiiv create draft failed: {resp.status} - {error}")
                        return None
                        
        except Exception as e:
            logger.error(f"Beehiiv API error: {e}")
            return None
    
    async def publish_draft(
        self,
        post_id: str,
        send_at: Optional[datetime] = None
    ) -> bool:
        """
        Publish or schedule a draft.
        
        Args:
            post_id: Draft post ID
            send_at: Optional scheduled send time (None = send now)
            
        Returns:
            True if successful
        """
        if not self.is_configured:
            return False
        
        url = f"{self.BASE_URL}/publications/{self.publication_id}/posts/{post_id}"
        
        payload = {"status": "confirmed"}
        
        if send_at:
            payload["scheduled_at"] = send_at.isoformat()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    url,
                    json=payload,
                    headers=self._get_headers()
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Beehiiv draft published: {post_id}")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"Beehiiv publish failed: {resp.status} - {error}")
                        return False
                        
        except Exception as e:
            logger.error(f"Beehiiv publish error: {e}")
            return False
    
    async def get_publication_stats(self) -> Dict[str, Any]:
        """
        Get publication statistics.
        
        Returns:
            Dict with publication stats
        """
        if not self.is_configured:
            return {}
        
        url = f"{self.BASE_URL}/publications/{self.publication_id}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._get_headers()
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pub = data.get("data", {})
                        return {
                            "name": pub.get("name"),
                            "subscriber_count": pub.get("subscriber_count", 0),
                            "post_count": pub.get("post_count", 0),
                            "created_at": pub.get("created_at")
                        }
                    else:
                        return {}
                        
        except Exception as e:
            logger.error(f"Beehiiv stats error: {e}")
            return {}
    
    async def publish_newsletter(
        self,
        title: str,
        markdown_content: str,
        schedule: Optional[datetime] = None
    ) -> Optional[str]:
        """
        Full publish flow: create draft and publish.
        
        Args:
            title: Newsletter title/subject
            markdown_content: Markdown content
            schedule: Optional scheduled time
            
        Returns:
            Post ID if successful
        """
        # Convert markdown to HTML (basic)
        html_content = self._markdown_to_html(markdown_content)
        
        # Create draft
        post_id = await self.create_draft(
            title=title,
            content_html=html_content
        )
        
        if post_id:
            # Publish or schedule
            success = await self.publish_draft(post_id, send_at=schedule)
            if success:
                return post_id
        
        return None
    
    def _markdown_to_html(self, markdown: str) -> str:
        """
        Basic markdown to HTML conversion.
        
        For production, use a proper markdown library.
        """
        import re
        
        html = markdown
        
        # Headers
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        
        # Bold and italic
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # Links
        html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)
        
        # Lists
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        
        # Paragraphs
        html = re.sub(r'\n\n', '</p><p>', html)
        html = f'<p>{html}</p>'
        
        # Horizontal rules
        html = html.replace('---', '<hr/>')
        
        return html


# Singleton instance
_publisher: Optional[BeehiivPublisher] = None


def get_beehiiv_publisher() -> BeehiivPublisher:
    """Get or create Beehiiv publisher instance."""
    global _publisher
    if _publisher is None:
        _publisher = BeehiivPublisher()
    return _publisher
