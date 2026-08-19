"""
Email Digest Service for Tech News Scraper

Enterprise feature that sends personalized email digests based on user preferences.

Features:
- SMTP email delivery with TLS support
- HTML email templates with Tokyo Night styling
- Personalized content based on topic subscriptions
- Daily/weekly scheduling options
- Article prioritization by relevance and sentiment
"""

import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path
import os
import json

logger = logging.getLogger(__name__)


@dataclass
class EmailConfig:
    """Email server configuration."""
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender_email: str = ""
    sender_password: str = ""
    sender_name: str = "Tech News Scraper"
    use_tls: bool = True
    
    @classmethod
    def from_env(cls) -> "EmailConfig":
        """Load config from environment variables."""
        return cls(
            smtp_server=os.getenv("SMTP_SERVER", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            sender_email=os.getenv("SMTP_EMAIL", ""),
            sender_password=os.getenv("SMTP_PASSWORD", ""),
            sender_name=os.getenv("SMTP_SENDER_NAME", "Tech News Scraper"),
            use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        )


@dataclass
class DigestArticle:
    """Article data for digest rendering."""
    title: str
    url: str
    source: str
    summary: str
    score: float = 0.0
    sentiment: str = "neutral"
    published_at: Optional[datetime] = None
    topics: List[str] = field(default_factory=list)


@dataclass
class DigestContent:
    """Complete digest content for rendering."""
    user_name: str
    period: str  # "daily" or "weekly"
    generated_at: datetime
    articles: List[DigestArticle]
    top_topics: List[str]
    sentiment_summary: Dict[str, float]
    total_articles_analyzed: int


class EmailDigestService:
    """
    Email Digest Service for personalized news delivery.
    
    Features:
    - SMTP email delivery with TLS
    - HTML email templates
    - Integration with UserPreferences
    - Article selection based on subscriptions
    """
    
    # Tokyo Night theme colors for email
    COLORS = {
        "bg": "#1a1b26",
        "bg_dark": "#16161e",
        "bg_highlight": "#292e42",
        "fg": "#c0caf5",
        "cyan": "#7dcfff",
        "blue": "#7aa2f7",
        "green": "#9ece6a",
        "orange": "#ff9e64",
        "red": "#f7768e",
        "purple": "#bb9af7",
    }
    
    def __init__(self, config: Optional[EmailConfig] = None):
        """Initialize email service."""
        self.config = config or EmailConfig.from_env()
        self._db_path = Path(__file__).parent.parent.parent / "data" / "digest_history.json"
        self._history: Dict[str, List[Dict]] = self._load_history()
        
        logger.info("EmailDigestService initialized")
    
    def _load_history(self) -> Dict[str, List[Dict]]:
        """Load digest send history."""
        if self._db_path.exists():
            try:
                with open(self._db_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"_load_history: suppressed {type(e).__name__}: {e}")
        return {}
    
    def _save_history(self):
        """Save digest send history."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._db_path, 'w') as f:
            json.dump(self._history, f, indent=2, default=str)
    
    def is_configured(self) -> bool:
        """Check if email service is properly configured."""
        return bool(self.config.sender_email and self.config.sender_password)
    
    def generate_digest(
        self,
        user_id: str,
        articles: List[Dict[str, Any]],
        period: str = "daily"
    ) -> DigestContent:
        """
        Generate digest content from articles based on user preferences.
        
        Args:
            user_id: User identifier
            articles: List of article dictionaries
            period: "daily" or "weekly"
            
        Returns:
            DigestContent ready for rendering
        """
        # Import preferences manager
        try:
            from src.user import get_preferences_manager
            prefs_manager = get_preferences_manager()
            prefs = prefs_manager.get_preferences(user_id)
        except Exception as e:
            logger.warning(f"Could not load preferences: {e}")
            prefs = None
        
        # Filter and score articles based on preferences
        scored_articles = []
        topic_counts: Dict[str, int] = {}
        sentiment_totals: Dict[str, float] = {"positive": 0, "neutral": 0, "negative": 0}
        
        for article in articles:
            relevance_score = self._calculate_relevance(article, prefs)
            
            # Track topics
            for topic in article.get("topics", []):
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            
            # Track sentiment
            sentiment = article.get("sentiment", "neutral")
            sentiment_totals[sentiment] = sentiment_totals.get(sentiment, 0) + 1
            
            if relevance_score > 0.3:  # Only include relevant articles
                scored_articles.append((relevance_score, article))
        
        # Sort by relevance and take top articles
        scored_articles.sort(key=lambda x: x[0], reverse=True)
        max_articles = 15 if period == "daily" else 30
        top_articles = scored_articles[:max_articles]
        
        # Convert to DigestArticle objects
        digest_articles = []
        for score, article in top_articles:
            digest_articles.append(DigestArticle(
                title=article.get("title", "Untitled"),
                url=article.get("url", ""),
                source=article.get("source", "Unknown"),
                summary=article.get("summary", "")[:200],
                score=score,
                sentiment=article.get("sentiment", "neutral"),
                published_at=article.get("published_at"),
                topics=article.get("topics", [])
            ))
        
        # Get top topics
        top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Calculate sentiment percentages
        total_sentiment = sum(sentiment_totals.values()) or 1
        sentiment_summary = {
            k: v / total_sentiment for k, v in sentiment_totals.items()
        }
        
        return DigestContent(
            user_name=prefs.user_id if prefs else user_id,
            period=period,
            generated_at=datetime.now(),
            articles=digest_articles,
            top_topics=[t[0] for t in top_topics],
            sentiment_summary=sentiment_summary,
            total_articles_analyzed=len(articles)
        )
    
    def _calculate_relevance(self, article: Dict, prefs) -> float:
        """Calculate relevance score based on user preferences."""
        score = 0.5  # Base score
        
        if not prefs:
            return score
        
        # Topic matching
        article_topics = set(t.lower() for t in article.get("topics", []))
        article_text = (article.get("title", "") + " " + article.get("summary", "")).lower()
        
        for topic_sub in prefs.topics:
            if topic_sub.enabled:
                if topic_sub.topic.lower() in article_topics or topic_sub.topic.lower() in article_text:
                    score += 0.2 * topic_sub.weight
        
        # Company watchlist matching
        for company in prefs.watchlist:
            if company.enabled and company.name.lower() in article_text:
                score += 0.3
                break
        
        return min(score, 1.0)
    
    def render_html(self, content: DigestContent) -> str:
        """Render digest content as HTML email."""
        c = self.COLORS
        
        # Build article cards HTML
        articles_html = ""
        for i, article in enumerate(content.articles):
            sentiment_color = {
                "positive": c["green"],
                "negative": c["red"],
                "neutral": c["fg"]
            }.get(article.sentiment, c["fg"])
            
            articles_html += f"""
            <tr>
                <td style="padding: 15px; background-color: {c['bg_highlight']}; border-radius: 8px; margin-bottom: 10px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td style="color: {c['cyan']}; font-size: 12px; padding-bottom: 5px;">
                                {article.source} • <span style="color: {sentiment_color};">{article.sentiment.upper()}</span>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding-bottom: 8px;">
                                <a href="{article.url}" style="color: {c['fg']}; font-size: 16px; font-weight: bold; text-decoration: none;">
                                    {article.title}
                                </a>
                            </td>
                        </tr>
                        <tr>
                            <td style="color: {c['fg']}; font-size: 14px; opacity: 0.8;">
                                {article.summary}
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            <tr><td style="height: 10px;"></td></tr>
            """
        
        # Sentiment bar
        pos_pct = int(content.sentiment_summary.get("positive", 0) * 100)
        neg_pct = int(content.sentiment_summary.get("negative", 0) * 100)
        neu_pct = 100 - pos_pct - neg_pct
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: {c['bg']}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: 0 auto; background-color: {c['bg_dark']};">
        
        <!-- Header -->
        <tr>
            <td style="background-color: {c['cyan']}; height: 4px;"></td>
        </tr>
        <tr>
            <td style="padding: 25px; text-align: center;">
                <h1 style="color: {c['fg']}; margin: 0; font-size: 24px;">
                    ⚡ Tech News Digest
                </h1>
                <p style="color: {c['cyan']}; margin: 10px 0 0; font-size: 14px;">
                    {content.period.capitalize()} Summary • {content.generated_at.strftime('%B %d, %Y')}
                </p>
            </td>
        </tr>
        
        <!-- Stats Bar -->
        <tr>
            <td style="padding: 0 20px 20px;">
                <table width="100%" cellpadding="10" cellspacing="0" style="background-color: {c['bg_highlight']}; border-radius: 8px;">
                    <tr>
                        <td style="text-align: center; color: {c['fg']};">
                            <div style="font-size: 24px; font-weight: bold; color: {c['blue']};">{len(content.articles)}</div>
                            <div style="font-size: 12px; opacity: 0.7;">Top Articles</div>
                        </td>
                        <td style="text-align: center; color: {c['fg']};">
                            <div style="font-size: 24px; font-weight: bold; color: {c['green']};">{content.total_articles_analyzed}</div>
                            <div style="font-size: 12px; opacity: 0.7;">Analyzed</div>
                        </td>
                        <td style="text-align: center; color: {c['fg']};">
                            <div style="font-size: 24px; font-weight: bold; color: {c['orange']};">{len(content.top_topics)}</div>
                            <div style="font-size: 12px; opacity: 0.7;">Topics</div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
        
        <!-- Sentiment Bar -->
        <tr>
            <td style="padding: 0 20px 20px;">
                <div style="font-size: 12px; color: {c['fg']}; margin-bottom: 5px; opacity: 0.7;">Market Sentiment</div>
                <div style="height: 8px; border-radius: 4px; overflow: hidden; display: flex;">
                    <div style="width: {pos_pct}%; background-color: {c['green']};"></div>
                    <div style="width: {neu_pct}%; background-color: {c['fg']}; opacity: 0.3;"></div>
                    <div style="width: {neg_pct}%; background-color: {c['red']};"></div>
                </div>
                <div style="font-size: 11px; color: {c['fg']}; margin-top: 5px; opacity: 0.6;">
                    🟢 {pos_pct}% Positive • ⚪ {neu_pct}% Neutral • 🔴 {neg_pct}% Negative
                </div>
            </td>
        </tr>
        
        <!-- Top Topics -->
        <tr>
            <td style="padding: 0 20px 20px;">
                <div style="font-size: 12px; color: {c['fg']}; margin-bottom: 8px; opacity: 0.7;">Trending Topics</div>
                <div>
                    {''.join(f'<span style="display: inline-block; background-color: {c["bg_highlight"]}; color: {c["cyan"]}; padding: 5px 12px; border-radius: 15px; margin: 3px; font-size: 12px;">{topic}</span>' for topic in content.top_topics)}
                </div>
            </td>
        </tr>
        
        <!-- Articles -->
        <tr>
            <td style="padding: 0 20px 20px;">
                <div style="font-size: 14px; color: {c['fg']}; margin-bottom: 15px; font-weight: bold;">
                    📰 Your Personalized Feed
                </div>
                <table width="100%" cellpadding="0" cellspacing="0">
                    {articles_html}
                </table>
            </td>
        </tr>
        
        <!-- Footer -->
        <tr>
            <td style="padding: 25px; text-align: center; background-color: {c['bg_highlight']};">
                <p style="color: {c['fg']}; font-size: 12px; margin: 0; opacity: 0.6;">
                    Tech News Scraper • Powered by AI<br>
                    <a href="#" style="color: {c['cyan']};">Unsubscribe</a> • 
                    <a href="#" style="color: {c['cyan']};">Manage Preferences</a>
                </p>
            </td>
        </tr>
    </table>
</body>
</html>
"""
        return html
    
    def render_plain_text(self, content: DigestContent) -> str:
        """Render digest as plain text fallback."""
        lines = [
            f"⚡ TECH NEWS DIGEST - {content.period.upper()}",
            f"Generated: {content.generated_at.strftime('%B %d, %Y %H:%M')}",
            "",
            f"📊 Stats: {len(content.articles)} top articles from {content.total_articles_analyzed} analyzed",
            f"📈 Trending: {', '.join(content.top_topics)}",
            "",
            "=" * 50,
            ""
        ]
        
        for i, article in enumerate(content.articles, 1):
            lines.extend([
                f"{i}. {article.title}",
                f"   Source: {article.source} | Sentiment: {article.sentiment}",
                f"   {article.summary}",
                f"   🔗 {article.url}",
                ""
            ])
        
        lines.extend([
            "=" * 50,
            "Tech News Scraper - Powered by AI",
            "Manage your preferences in the app settings."
        ])
        
        return "\n".join(lines)
    
    def send_digest(
        self,
        recipient_email: str,
        content: DigestContent,
        user_id: str = "default"
    ) -> bool:
        """
        Send email digest to recipient.
        
        Args:
            recipient_email: Recipient email address
            content: DigestContent to send
            user_id: User ID for history tracking
            
        Returns:
            True if sent successfully
        """
        if not self.is_configured():
            logger.error("Email service not configured. Set SMTP_EMAIL and SMTP_PASSWORD.")
            return False
        
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = f"⚡ Your {content.period.capitalize()} Tech News Digest - {content.generated_at.strftime('%b %d')}"
            message["From"] = f"{self.config.sender_name} <{self.config.sender_email}>"
            message["To"] = recipient_email
            
            # Attach plain text and HTML versions
            part1 = MIMEText(self.render_plain_text(content), "plain")
            part2 = MIMEText(self.render_html(content), "html")
            
            message.attach(part1)
            message.attach(part2)
            
            # Send email
            context = ssl.create_default_context()
            
            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port) as server:
                if self.config.use_tls:
                    server.starttls(context=context)
                server.login(self.config.sender_email, self.config.sender_password)
                server.sendmail(self.config.sender_email, recipient_email, message.as_string())
            
            # Record in history
            self._record_send(user_id, recipient_email, content)
            
            logger.info(f"Digest sent successfully to {recipient_email}")
            return True
            
        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP authentication failed. Check email and password.")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send digest: {e}")
            return False
    
    def _record_send(self, user_id: str, recipient: str, content: DigestContent):
        """Record digest send in history."""
        if user_id not in self._history:
            self._history[user_id] = []
        
        self._history[user_id].append({
            "sent_at": datetime.now().isoformat(),
            "recipient": recipient,
            "period": content.period,
            "article_count": len(content.articles)
        })
        
        # Keep only last 100 entries per user
        self._history[user_id] = self._history[user_id][-100:]
        self._save_history()
    
    def get_last_send(self, user_id: str) -> Optional[datetime]:
        """Get last digest send time for user."""
        if user_id in self._history and self._history[user_id]:
            last = self._history[user_id][-1]
            return datetime.fromisoformat(last["sent_at"])
        return None
    
    def should_send_digest(self, user_id: str, period: str = "daily") -> bool:
        """Check if it's time to send a digest based on schedule."""
        last_send = self.get_last_send(user_id)
        
        if not last_send:
            return True
        
        now = datetime.now()
        if period == "daily":
            return (now - last_send) >= timedelta(hours=23)
        elif period == "weekly":
            return (now - last_send) >= timedelta(days=6, hours=23)
        
        return False


# Singleton instance
_email_service: Optional[EmailDigestService] = None


def get_email_service() -> EmailDigestService:
    """Get singleton EmailDigestService instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailDigestService()
    return _email_service
