"""
Alert Engine for Tech News Scraper v3.0

Criticality-based alerting system with:
- Configurable thresholds
- Multiple channel support (GUI, Telegram, Discord, Email)
- Channel configuration UI placeholders
- Alert deduplication
"""

import asyncio
import hashlib
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    """Alert severity levels mapped to criticality scores."""
    CRITICAL = "critical"  # 9-10
    HIGH = "high"          # 7-8
    MEDIUM = "medium"      # 4-6
    LOW = "low"            # 1-3
    
    @classmethod
    def from_criticality(cls, score: int) -> "AlertLevel":
        """Convert criticality score to alert level."""
        if score >= 9:
            return cls.CRITICAL
        elif score >= 7:
            return cls.HIGH
        elif score >= 4:
            return cls.MEDIUM
        else:
            return cls.LOW
    
    @property
    def emoji(self) -> str:
        """Get emoji for alert level."""
        return {
            AlertLevel.CRITICAL: "🔴",
            AlertLevel.HIGH: "🟠",
            AlertLevel.MEDIUM: "🟡",
            AlertLevel.LOW: "🟢",
        }[self]
    
    @property
    def color(self) -> str:
        """Get hex color for alert level."""
        return {
            AlertLevel.CRITICAL: "#dc2626",
            AlertLevel.HIGH: "#f97316",
            AlertLevel.MEDIUM: "#eab308",
            AlertLevel.LOW: "#22c55e",
        }[self]


class ChannelType(str, Enum):
    """Supported alert channels."""
    GUI = "gui"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    EMAIL = "email"
    MACOS_NOTIFICATION = "macos"
    WEBHOOK = "webhook"


@dataclass
class ChannelConfig:
    """
    Configuration for an alert channel.
    
    Includes setup status and required credentials.
    """
    channel_type: ChannelType
    enabled: bool = False
    configured: bool = False
    
    # Channel-specific settings (stored as dict for flexibility)
    settings: Dict[str, Any] = field(default_factory=dict)
    
    # UI metadata
    display_name: str = ""
    description: str = ""
    setup_url: str = ""
    required_fields: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.channel_type.value.capitalize()


# Default channel configurations with setup instructions
DEFAULT_CHANNEL_CONFIGS = {
    ChannelType.GUI: ChannelConfig(
        channel_type=ChannelType.GUI,
        enabled=True,
        configured=True,
        display_name="In-App Notifications",
        description="Display alerts in the GUI application. No setup required.",
        required_fields=[]
    ),
    ChannelType.TELEGRAM: ChannelConfig(
        channel_type=ChannelType.TELEGRAM,
        enabled=False,
        configured=False,
        display_name="Telegram Bot",
        description="Receive alerts via Telegram. Create a bot with @BotFather and get your chat ID.",
        setup_url="https://core.telegram.org/bots#creating-a-new-bot",
        required_fields=["bot_token", "chat_id"]
    ),
    ChannelType.DISCORD: ChannelConfig(
        channel_type=ChannelType.DISCORD,
        enabled=False,
        configured=False,
        display_name="Discord Webhook",
        description="Post alerts to a Discord channel. Create a webhook in your server settings.",
        setup_url="https://support.discord.com/hc/en-us/articles/228383668",
        required_fields=["webhook_url"]
    ),
    ChannelType.EMAIL: ChannelConfig(
        channel_type=ChannelType.EMAIL,
        enabled=False,
        configured=False,
        display_name="Email Notifications",
        description="Send alerts via email. Supports SMTP or SendGrid API.",
        setup_url="",
        required_fields=["smtp_host", "smtp_port", "smtp_user", "smtp_password", "to_address"]
    ),
    ChannelType.MACOS_NOTIFICATION: ChannelConfig(
        channel_type=ChannelType.MACOS_NOTIFICATION,
        enabled=False,
        configured=False,
        display_name="macOS Notifications",
        description="Native macOS notification center. Requires osascript.",
        required_fields=[]
    ),
    ChannelType.WEBHOOK: ChannelConfig(
        channel_type=ChannelType.WEBHOOK,
        enabled=False,
        configured=False,
        display_name="Custom Webhook",
        description="POST alerts to a custom HTTP endpoint.",
        required_fields=["url", "headers"]
    ),
}


class Alert(BaseModel):
    """Alert data model."""
    id: str = Field(description="Unique alert ID")
    article_id: str = Field(description="Reference to article ID")
    article_title: str
    article_url: str
    
    level: AlertLevel
    criticality: int = Field(ge=1, le=10)
    
    justification: str
    affected_markets: List[str] = Field(default_factory=list)
    affected_companies: List[str] = Field(default_factory=list)
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sent_channels: List[str] = Field(default_factory=list)
    
    @classmethod
    def from_analysis(
        cls,
        article_id: str,
        article_title: str,
        article_url: str,
        criticality: int,
        justification: str,
        affected_markets: List[str],
        affected_companies: List[str]
    ) -> "Alert":
        """Create alert from disruption analysis."""
        alert_id = hashlib.md5(
            f"{article_id}:{criticality}".encode()
        ).hexdigest()[:12]
        
        return cls(
            id=alert_id,
            article_id=article_id,
            article_title=article_title,
            article_url=article_url,
            level=AlertLevel.from_criticality(criticality),
            criticality=criticality,
            justification=justification,
            affected_markets=affected_markets,
            affected_companies=affected_companies
        )
    
    def format_message(self, include_emoji: bool = True) -> str:
        """Format alert as human-readable message."""
        emoji = self.level.emoji if include_emoji else ""
        
        message = f"{emoji} {self.level.value.upper()} ALERT (Criticality: {self.criticality}/10)\n\n"
        message += f"📰 {self.article_title}\n\n"
        message += f"💡 {self.justification}\n\n"
        
        if self.affected_markets:
            message += f"📊 Markets: {', '.join(self.affected_markets[:3])}\n"
        if self.affected_companies:
            message += f"🏢 Companies: {', '.join(self.affected_companies[:3])}\n"
        
        message += f"\n🔗 {self.article_url}"
        
        return message


@dataclass
class AlertConfig:
    """Global alert configuration."""
    
    # Thresholds for each level
    critical_threshold: int = 9
    high_threshold: int = 7
    medium_threshold: int = 4
    
    # Minimum level to send alerts (alerts below this are GUI-only)
    min_external_alert_level: AlertLevel = AlertLevel.HIGH
    
    # Deduplication
    dedup_window_hours: int = 24
    
    # Rate limiting
    max_alerts_per_hour: int = 20
    
    # Channel configurations
    channels: Dict[ChannelType, ChannelConfig] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.channels:
            self.channels = DEFAULT_CHANNEL_CONFIGS.copy()


class AlertChannel(ABC):
    """Abstract base class for alert channels."""
    
    @abstractmethod
    async def send(self, alert: Alert) -> bool:
        """Send an alert. Returns True if successful."""
        pass
    
    @abstractmethod
    def is_configured(self) -> bool:
        """Check if channel is properly configured."""
        pass
    
    @property
    @abstractmethod
    def channel_type(self) -> ChannelType:
        """Get the channel type."""
        pass


class GUIAlertChannel(AlertChannel):
    """In-app GUI notifications."""
    
    def __init__(self):
        self._callbacks: List[Callable[[Alert], None]] = []
        self._alert_queue: List[Alert] = []
    
    def register_callback(self, callback: Callable[[Alert], None]):
        """Register a callback for when alerts are received."""
        self._callbacks.append(callback)
    
    async def send(self, alert: Alert) -> bool:
        """Send alert to GUI callbacks."""
        self._alert_queue.append(alert)
        
        for callback in self._callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"GUI alert callback failed: {e}")
        
        return True
    
    def get_pending_alerts(self) -> List[Alert]:
        """Get and clear pending alerts."""
        alerts = self._alert_queue.copy()
        self._alert_queue.clear()
        return alerts
    
    def is_configured(self) -> bool:
        return True
    
    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.GUI


class TelegramAlertChannel(AlertChannel):
    """Telegram bot notifications."""
    
    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
    
    async def send(self, alert: Alert) -> bool:
        """Send alert via Telegram."""
        if not self.is_configured():
            logger.warning("Telegram not configured")
            return False
        
        try:
            import aiohttp
            
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": alert.format_message(),
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.info(f"Telegram alert sent: {alert.id}")
                        return True
                    else:
                        logger.error(f"Telegram API error: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False
    
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)
    
    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.TELEGRAM


class DiscordAlertChannel(AlertChannel):
    """Discord webhook notifications."""
    
    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
    
    async def send(self, alert: Alert) -> bool:
        """Send alert via Discord webhook."""
        if not self.is_configured():
            logger.warning("Discord not configured")
            return False
        
        try:
            import aiohttp
            
            embed = {
                "title": f"{alert.level.emoji} {alert.article_title}",
                "description": alert.justification,
                "color": int(alert.level.color.lstrip("#"), 16),
                "fields": [
                    {
                        "name": "Criticality",
                        "value": f"{alert.criticality}/10",
                        "inline": True
                    },
                    {
                        "name": "Level",
                        "value": alert.level.value.upper(),
                        "inline": True
                    }
                ],
                "url": alert.article_url,
                "timestamp": alert.created_at.isoformat()
            }
            
            if alert.affected_markets:
                embed["fields"].append({
                    "name": "Affected Markets",
                    "value": ", ".join(alert.affected_markets[:5]),
                    "inline": False
                })
            
            payload = {"embeds": [embed]}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as response:
                    if response.status in (200, 204):
                        logger.info(f"Discord alert sent: {alert.id}")
                        return True
                    else:
                        logger.error(f"Discord webhook error: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Failed to send Discord alert: {e}")
            return False
    
    def is_configured(self) -> bool:
        return bool(self.webhook_url)
    
    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.DISCORD


class MacOSNotificationChannel(AlertChannel):
    """macOS native notifications via osascript."""
    
    async def send(self, alert: Alert) -> bool:
        """Send alert via macOS notification center."""
        try:
            import subprocess
            
            title = f"{alert.level.emoji} {alert.level.value.upper()} Alert"
            message = alert.article_title[:100]
            
            script = f'''
            display notification "{message}" with title "{title}" sound name "default"
            '''
            
            process = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"macOS notification sent: {alert.id}")
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"Failed to send macOS notification: {e}")
            return False
    
    def is_configured(self) -> bool:
        # Available on macOS by default
        import platform
        return platform.system() == "Darwin"
    
    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.MACOS_NOTIFICATION


class AlertEngine:
    """
    Main alert engine for processing and dispatching alerts.
    
    Features:
    - Criticality-based filtering
    - Multi-channel dispatch
    - Deduplication
    - Rate limiting
    """
    
    def __init__(self, config: Optional[AlertConfig] = None):
        self.config = config or AlertConfig()
        
        # Initialize channels
        self._channels: Dict[ChannelType, AlertChannel] = {
            ChannelType.GUI: GUIAlertChannel(),
            ChannelType.TELEGRAM: TelegramAlertChannel(),
            ChannelType.DISCORD: DiscordAlertChannel(),
            ChannelType.MACOS_NOTIFICATION: MacOSNotificationChannel(),
        }
        
        # Deduplication tracking
        self._sent_alert_ids: Set[str] = set()
        self._alert_timestamps: List[datetime] = []
    
    @property
    def gui_channel(self) -> GUIAlertChannel:
        """Get the GUI channel for registering callbacks."""
        return self._channels[ChannelType.GUI]
    
    def get_channel_configs(self) -> List[ChannelConfig]:
        """Get all channel configurations for UI display."""
        return list(self.config.channels.values())
    
    def update_channel_config(
        self,
        channel_type: ChannelType,
        enabled: bool = None,
        settings: Dict[str, Any] = None
    ):
        """Update channel configuration."""
        if channel_type not in self.config.channels:
            return
        
        channel_config = self.config.channels[channel_type]
        
        if enabled is not None:
            channel_config.enabled = enabled
        
        if settings:
            channel_config.settings.update(settings)
            
            # Check if all required fields are provided
            required = channel_config.required_fields
            channel_config.configured = all(
                settings.get(field) for field in required
            )
            
            # Update the actual channel with new settings
            self._update_channel_credentials(channel_type, settings)
    
    def _update_channel_credentials(
        self,
        channel_type: ChannelType,
        settings: Dict[str, Any]
    ):
        """Update channel credentials from settings."""
        if channel_type == ChannelType.TELEGRAM:
            channel = self._channels[ChannelType.TELEGRAM]
            channel.bot_token = settings.get("bot_token", "")
            channel.chat_id = settings.get("chat_id", "")
            
        elif channel_type == ChannelType.DISCORD:
            channel = self._channels[ChannelType.DISCORD]
            channel.webhook_url = settings.get("webhook_url", "")
    
    def should_alert(self, criticality: int) -> bool:
        """Check if an alert should be generated based on criticality."""
        return criticality >= self.config.medium_threshold
    
    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits."""
        now = datetime.now(UTC)
        hour_ago = now - timedelta(hours=1)
        
        # Clean old timestamps
        self._alert_timestamps = [
            ts for ts in self._alert_timestamps
            if ts > hour_ago
        ]
        
        return len(self._alert_timestamps) < self.config.max_alerts_per_hour
    
    def _is_duplicate(self, alert_id: str) -> bool:
        """Check if alert is a duplicate."""
        return alert_id in self._sent_alert_ids
    
    async def evaluate_and_dispatch(
        self,
        article_id: str,
        article_title: str,
        article_url: str,
        criticality: int,
        justification: str,
        affected_markets: List[str] = None,
        affected_companies: List[str] = None
    ) -> Optional[Alert]:
        """
        Evaluate if an alert should be sent and dispatch it.
        
        Args:
            article_id: Unique article identifier
            article_title: Article title
            article_url: Article URL
            criticality: Criticality score (1-10)
            justification: Reason for the criticality
            affected_markets: List of affected markets
            affected_companies: List of affected companies
            
        Returns:
            Alert if dispatched, None otherwise
        """
        if not self.should_alert(criticality):
            return None
        
        alert = Alert.from_analysis(
            article_id=article_id,
            article_title=article_title,
            article_url=article_url,
            criticality=criticality,
            justification=justification,
            affected_markets=affected_markets or [],
            affected_companies=affected_companies or []
        )
        
        # Check deduplication
        if self._is_duplicate(alert.id):
            logger.debug(f"Skipping duplicate alert: {alert.id}")
            return None
        
        # Check rate limit
        if not self._check_rate_limit():
            logger.warning("Alert rate limit exceeded")
            return None
        
        # Dispatch to channels
        await self.dispatch(alert)
        
        # Track
        self._sent_alert_ids.add(alert.id)
        self._alert_timestamps.append(datetime.now(UTC))
        
        return alert
    
    async def dispatch(self, alert: Alert):
        """Dispatch alert to all enabled channels."""
        
        # Always send to GUI
        gui_channel = self._channels[ChannelType.GUI]
        await gui_channel.send(alert)
        alert.sent_channels.append(ChannelType.GUI.value)
        
        # Check if external alerts are enabled for this level
        SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        alert_val = getattr(alert.level, "value", str(alert.level)).lower()
        min_val = getattr(self.config.min_external_alert_level, "value", str(self.config.min_external_alert_level)).lower()
        if SEVERITY_RANK.get(alert_val, 0) < SEVERITY_RANK.get(min_val, 0):
            return
        
        # Send to other enabled channels
        for channel_type, channel_config in self.config.channels.items():
            if channel_type == ChannelType.GUI:
                continue
            
            if not channel_config.enabled or not channel_config.configured:
                continue
            
            channel = self._channels.get(channel_type)
            if channel and channel.is_configured():
                try:
                    success = await channel.send(alert)
                    if success:
                        alert.sent_channels.append(channel_type.value)
                except Exception as e:
                    logger.error(f"Failed to send to {channel_type}: {e}")


# Default alert engine instance
_default_engine: Optional[AlertEngine] = None


def get_alert_engine() -> AlertEngine:
    """Get or create the default alert engine."""
    global _default_engine
    if _default_engine is None:
        _default_engine = AlertEngine()
    return _default_engine
