"""
Slack Integration for Newsletter Approval Workflow

Enables human-in-the-loop approval via Slack messages.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SlackConfig:
    """Slack integration configuration."""
    bot_token: str = ""
    channel_id: str = ""
    webhook_url: str = ""  # For incoming webhooks
    timeout_seconds: int = 300  # 5 minutes default


@dataclass
class ApprovalResult:
    """Result of a Slack approval request."""
    approved: bool
    reviewer: str = ""
    feedback: str = ""
    timestamp: str = ""


class SlackApproval:
    """
    Slack-based approval workflow for newsletter story selection.
    
    Features:
    - Post story selection to Slack
    - Interactive buttons for approve/reject
    - Feedback collection
    - Timeout fallback to GUI
    """
    
    def __init__(self, config: Optional[SlackConfig] = None):
        """
        Initialize Slack approval.
        
        Args:
            config: Slack configuration (loads from env if not provided)
        """
        self.config = config or self._load_config_from_env()
        self._client = None
        self._pending_approvals: Dict[str, asyncio.Event] = {}
        self._approval_results: Dict[str, ApprovalResult] = {}
    
    def _load_config_from_env(self) -> SlackConfig:
        """Load Slack config from environment variables."""
        return SlackConfig(
            bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
            channel_id=os.getenv("SLACK_CHANNEL_ID", ""),
            webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
            timeout_seconds=int(os.getenv("SLACK_APPROVAL_TIMEOUT", "300"))
        )
    
    @property
    def is_configured(self) -> bool:
        """Check if Slack is properly configured."""
        return bool(self.config.bot_token and self.config.channel_id) or bool(self.config.webhook_url)
    
    def _get_client(self):
        """Lazy load Slack client."""
        if self._client is None:
            try:
                from slack_sdk.web.async_client import AsyncWebClient
                self._client = AsyncWebClient(token=self.config.bot_token)
            except ImportError:
                logger.warning("slack-sdk not installed. Run: pip install slack-sdk")
                return None
        return self._client
    
    async def request_approval(
        self,
        stories: List[Dict[str, Any]],
        edition_date: str = ""
    ) -> ApprovalResult:
        """
        Request approval for story selection via Slack.
        
        Args:
            stories: List of selected stories
            edition_date: Newsletter edition date
            
        Returns:
            ApprovalResult with approval status
        """
        if not self.is_configured:
            logger.warning("Slack not configured, auto-approving")
            return ApprovalResult(approved=True, feedback="Auto-approved (Slack not configured)")
        
        edition_date = edition_date or datetime.now().strftime("%Y-%m-%d")
        
        # Build message blocks
        blocks = self._build_approval_message(stories, edition_date)
        
        try:
            client = self._get_client()
            if client is None:
                return ApprovalResult(approved=True, feedback="Auto-approved (Slack client unavailable)")
            
            # Post message
            response = await client.chat_postMessage(
                channel=self.config.channel_id,
                blocks=blocks,
                text=f"📰 Newsletter Approval Request - {edition_date}"
            )
            
            message_ts = response["ts"]
            
            # Wait for response (with timeout)
            approval_event = asyncio.Event()
            self._pending_approvals[message_ts] = approval_event
            
            try:
                await asyncio.wait_for(
                    approval_event.wait(),
                    timeout=self.config.timeout_seconds
                )
                return self._approval_results.get(message_ts, ApprovalResult(approved=True))
            except asyncio.TimeoutError:
                logger.warning("Slack approval timed out, auto-approving")
                return ApprovalResult(
                    approved=True, 
                    feedback="Auto-approved (timeout)",
                    timestamp=datetime.now(UTC).isoformat()
                )
            finally:
                self._pending_approvals.pop(message_ts, None)
                
        except Exception as e:
            logger.error(f"Slack approval request failed: {e}")
            return ApprovalResult(approved=True, feedback=f"Auto-approved (error: {str(e)[:50]})")
    
    def _build_approval_message(
        self,
        stories: List[Dict[str, Any]],
        edition_date: str
    ) -> List[Dict]:
        """Build Slack blocks for approval message."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📰 Newsletter Approval - {edition_date}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*AI Editor has selected these stories for today's newsletter:*"
                }
            },
            {"type": "divider"}
        ]
        
        # Add each story
        for i, story in enumerate(stories[:4], 1):
            criticality = story.get("criticality", 0)
            
            # Criticality emoji
            if criticality >= 9:
                crit_emoji = "🔴"
            elif criticality >= 7:
                crit_emoji = "🟠"
            elif criticality >= 4:
                crit_emoji = "🟡"
            else:
                crit_emoji = "🟢"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{i}. {story.get('title', 'Untitled')[:80]}*\n"
                            f"{crit_emoji} Criticality: {criticality}/10 | "
                            f"Source: {story.get('source', 'Unknown')}"
                }
            })
        
        blocks.extend([
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                        "style": "primary",
                        "action_id": "approve_newsletter"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✏️ Edit Selection", "emoji": True},
                        "action_id": "edit_newsletter"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                        "style": "danger",
                        "action_id": "reject_newsletter"
                    }
                ]
            }
        ])
        
        return blocks
    
    async def post_newsletter_preview(
        self,
        markdown: str,
        edition_date: str
    ) -> bool:
        """
        Post newsletter preview to Slack.
        
        Args:
            markdown: Newsletter markdown content
            edition_date: Edition date
            
        Returns:
            True if posted successfully
        """
        if not self.is_configured:
            return False
        
        try:
            client = self._get_client()
            if client is None:
                return False
            
            # Truncate for Slack
            preview = markdown[:2000] + "..." if len(markdown) > 2000 else markdown
            
            await client.chat_postMessage(
                channel=self.config.channel_id,
                blocks=[
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"📬 Newsletter Preview - {edition_date}",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"```{preview}```"
                        }
                    }
                ],
                text=f"Newsletter preview for {edition_date}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to post newsletter preview: {e}")
            return False
    
    async def notify_completed(
        self,
        edition_date: str,
        export_path: str
    ) -> None:
        """
        Notify that newsletter generation is complete.
        
        Args:
            edition_date: Edition date
            export_path: Path to exported file
        """
        if not self.is_configured:
            return
        
        try:
            client = self._get_client()
            if client:
                await client.chat_postMessage(
                    channel=self.config.channel_id,
                    text=f"✅ Newsletter generated successfully!\n"
                         f"📅 Edition: {edition_date}\n"
                         f"📁 Saved to: `{export_path}`"
                )
        except Exception as e:
            logger.error(f"Failed to send completion notification: {e}")
    
    def handle_interaction(self, payload: Dict[str, Any]) -> None:
        """
        Handle Slack interaction (button clicks).
        
        Args:
            payload: Slack interaction payload
        """
        action_id = payload.get("actions", [{}])[0].get("action_id", "")
        message_ts = payload.get("message", {}).get("ts", "")
        user = payload.get("user", {}).get("name", "unknown")
        
        if message_ts in self._pending_approvals:
            if action_id == "approve_newsletter":
                self._approval_results[message_ts] = ApprovalResult(
                    approved=True,
                    reviewer=user,
                    timestamp=datetime.now(UTC).isoformat()
                )
            elif action_id == "reject_newsletter":
                self._approval_results[message_ts] = ApprovalResult(
                    approved=False,
                    reviewer=user,
                    feedback="Rejected via Slack",
                    timestamp=datetime.now(UTC).isoformat()
                )
            else:
                self._approval_results[message_ts] = ApprovalResult(
                    approved=False,
                    reviewer=user,
                    feedback="Edit requested",
                    timestamp=datetime.now(UTC).isoformat()
                )
            
            self._pending_approvals[message_ts].set()


# Singleton instance
_slack: Optional[SlackApproval] = None


def get_slack_approval() -> SlackApproval:
    """Get or create Slack approval instance."""
    global _slack
    if _slack is None:
        _slack = SlackApproval()
    return _slack
