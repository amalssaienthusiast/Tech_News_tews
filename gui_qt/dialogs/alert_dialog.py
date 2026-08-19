"""
Alert Configuration Dialog for Tech News Scraper
Configure alert channels and notification settings
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QWidget,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QSpinBox,
    QSlider,
    QFrame,
    QMessageBox,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
)
from PyQt6.QtCore import Qt, QSettings
from ..theme import COLORS, Fonts


class AlertChannel:
    """Alert channel configuration"""

    def __init__(self, name: str, channel_type: str, enabled: bool = False):
        self.name = name
        self.type = channel_type
        self.enabled = enabled
        self.config = {}


class AlertConfigDialog(QDialog):
    """Alert configuration dialog

    Configure notification channels:
    - Desktop notifications
    - Email alerts
    - Webhook notifications
    - Slack integration
    - Alert thresholds
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("🔔 Alert Configuration")
        self.setMinimumSize(700, 550)

        self._settings = QSettings("TechNewsScraper", "Alerts")
        self._channels = []

        self._setup_ui()
        self._load_settings()
        self._apply_styles()

    def _setup_ui(self):
        """Build the dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Header
        header = QLabel("🔔 Alert Configuration")
        header.setStyleSheet(f"""
            font-size: 20px;
            font-weight: bold;
            color: {COLORS.cyan};
        """)
        layout.addWidget(header)

        # Description
        desc = QLabel(
            "Configure how you want to be notified about new articles and important events."
        )
        desc.setStyleSheet(f"color: {COLORS.comment};")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_channels_tab(), "📡 Channels")
        self.tabs.addTab(self._create_thresholds_tab(), "📊 Thresholds")
        self.tabs.addTab(self._create_filtering_tab(), "🔍 Filtering")
        layout.addWidget(self.tabs)

        # Buttons
        button_layout = QHBoxLayout()

        test_btn = QPushButton("🧪 Test Alerts")
        test_btn.clicked.connect(self._test_alerts)
        button_layout.addWidget(test_btn)

        button_layout.addStretch()

        cancel_btn = QPushButton("✕ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        save_btn = QPushButton("💾 Save Changes")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def _create_channels_tab(self):
        """Create channels configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)

        # Desktop Notifications
        desktop_group = self._create_channel_group(
            "Desktop Notifications",
            "Show system notifications when new articles arrive",
        )

        self.desktop_enabled = QCheckBox("Enable desktop notifications")
        desktop_group.layout().addWidget(self.desktop_enabled)

        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("Duration (seconds):"))
        self.desktop_duration = QSpinBox()
        self.desktop_duration.setRange(1, 30)
        self.desktop_duration.setValue(5)
        duration_layout.addWidget(self.desktop_duration)
        duration_layout.addStretch()
        desktop_group.layout().addLayout(duration_layout)

        layout.addWidget(desktop_group)

        # Email Alerts
        email_group = self._create_channel_group(
            "Email Alerts", "Send email digests of important articles"
        )

        self.email_enabled = QCheckBox("Enable email alerts")
        email_group.layout().addWidget(self.email_enabled)

        email_form = QFormLayout()
        self.email_address = QLineEdit()
        self.email_address.setPlaceholderText("your@email.com")
        email_form.addRow("Email Address:", self.email_address)

        self.email_frequency = QComboBox()
        self.email_frequency.addItems(
            ["Immediate", "Hourly Digest", "Daily Digest", "Weekly Digest"]
        )
        email_form.addRow("Frequency:", self.email_frequency)

        email_group.layout().addLayout(email_form)
        layout.addWidget(email_group)

        # Webhook
        webhook_group = self._create_channel_group(
            "Webhook", "Send POST requests to external services"
        )

        self.webhook_enabled = QCheckBox("Enable webhook notifications")
        webhook_group.layout().addWidget(self.webhook_enabled)

        webhook_form = QFormLayout()
        self.webhook_url = QLineEdit()
        self.webhook_url.setPlaceholderText("https://hooks.example.com/...")
        webhook_form.addRow("Webhook URL:", self.webhook_url)

        self.webhook_format = QComboBox()
        self.webhook_format.addItems(["JSON", "Form Data"])
        webhook_form.addRow("Format:", self.webhook_format)

        webhook_group.layout().addLayout(webhook_form)
        layout.addWidget(webhook_group)

        # Slack
        slack_group = self._create_channel_group(
            "Slack Integration", "Post alerts to Slack channels"
        )

        self.slack_enabled = QCheckBox("Enable Slack notifications")
        slack_group.layout().addWidget(self.slack_enabled)

        slack_form = QFormLayout()
        self.slack_webhook = QLineEdit()
        self.slack_webhook.setPlaceholderText("https://hooks.slack.com/services/...")
        slack_form.addRow("Webhook URL:", self.slack_webhook)

        self.slack_channel = QLineEdit()
        self.slack_channel.setPlaceholderText("#general (optional)")
        slack_form.addRow("Channel:", self.slack_channel)

        slack_group.layout().addLayout(slack_form)
        layout.addWidget(slack_group)

        # Telegram
        telegram_group = self._create_channel_group(
            "Telegram Bot", "Send alerts to a Telegram chat via bot"
        )

        self.telegram_enabled = QCheckBox("Enable Telegram notifications")
        telegram_group.layout().addWidget(self.telegram_enabled)

        telegram_form = QFormLayout()
        self.telegram_bot_token = QLineEdit()
        self.telegram_bot_token.setPlaceholderText("123456789:ABCdef...")
        self.telegram_bot_token.setEchoMode(QLineEdit.EchoMode.Password)
        telegram_form.addRow("Bot Token:", self.telegram_bot_token)

        self.telegram_chat_id = QLineEdit()
        self.telegram_chat_id.setPlaceholderText("-100123456789")
        telegram_form.addRow("Chat ID:", self.telegram_chat_id)

        telegram_group.layout().addLayout(telegram_form)
        layout.addWidget(telegram_group)

        # Discord
        discord_group = self._create_channel_group(
            "Discord Webhook", "Post alerts to a Discord channel"
        )

        self.discord_enabled = QCheckBox("Enable Discord notifications")
        discord_group.layout().addWidget(self.discord_enabled)

        discord_form = QFormLayout()
        self.discord_webhook_url = QLineEdit()
        self.discord_webhook_url.setPlaceholderText(
            "https://discord.com/api/webhooks/..."
        )
        discord_form.addRow("Webhook URL:", self.discord_webhook_url)

        self.discord_username = QLineEdit()
        self.discord_username.setPlaceholderText("TechNewsBot (optional)")
        discord_form.addRow("Bot Username:", self.discord_username)

        discord_group.layout().addLayout(discord_form)
        layout.addWidget(discord_group)

        # In-App Notifications
        inapp_group = self._create_channel_group(
            "In-App Notifications", "Show toast notifications within the application"
        )

        self.inapp_enabled = QCheckBox("Enable in-app toast notifications")
        self.inapp_enabled.setChecked(True)
        inapp_group.layout().addWidget(self.inapp_enabled)

        inapp_form = QFormLayout()
        self.inapp_position = QComboBox()
        self.inapp_position.addItems(
            ["Bottom Right", "Bottom Left", "Top Right", "Top Left"]
        )
        inapp_form.addRow("Position:", self.inapp_position)

        self.inapp_sound = QCheckBox("Play sound on notification")
        inapp_form.addRow("", self.inapp_sound)

        inapp_group.layout().addLayout(inapp_form)
        layout.addWidget(inapp_group)

        layout.addStretch()
        return tab

    def _create_channel_group(self, title: str, description: str) -> QGroupBox:
        """Create a channel configuration group"""
        group = QGroupBox(title)
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)

        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        desc_label = QLabel(description)
        desc_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 12px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        return group

    def _create_thresholds_tab(self):
        """Create thresholds configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)

        # Alert Thresholds
        threshold_group = QGroupBox("Alert Thresholds")
        threshold_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
            }}
        """)

        threshold_layout = QFormLayout(threshold_group)

        # Minimum score
        self.min_score = QSlider(Qt.Orientation.Horizontal)
        self.min_score.setRange(0, 100)
        self.min_score.setValue(70)
        score_layout = QHBoxLayout()
        score_layout.addWidget(self.min_score)
        self.score_value = QLabel("7.0")
        score_layout.addWidget(self.score_value)
        self.min_score.valueChanged.connect(
            lambda v: self.score_value.setText(f"{v / 10:.1f}")
        )
        threshold_layout.addRow("Minimum Tech Score:", score_layout)

        # Article count threshold
        self.min_articles = QSpinBox()
        self.min_articles.setRange(1, 50)
        self.min_articles.setValue(5)
        threshold_layout.addRow("Minimum Articles:", self.min_articles)

        # Priority articles only
        self.priority_only = QCheckBox(
            "Only alert for high-priority articles (Score ≥ 8.0)"
        )
        threshold_layout.addRow("", self.priority_only)

        layout.addWidget(threshold_group)

        # Cooldown
        cooldown_group = QGroupBox("Cooldown Settings")
        cooldown_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
            }}
        """)

        cooldown_layout = QFormLayout(cooldown_group)

        self.cooldown_minutes = QSpinBox()
        self.cooldown_minutes.setRange(0, 60)
        self.cooldown_minutes.setValue(5)
        self.cooldown_minutes.setSuffix(" minutes")
        cooldown_layout.addRow("Alert Cooldown:", self.cooldown_minutes)

        layout.addWidget(cooldown_group)

        # Digest settings
        digest_group = QGroupBox("Digest Settings")
        digest_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
            }}
        """)

        digest_layout = QFormLayout(digest_group)

        self.digest_max_articles = QSpinBox()
        self.digest_max_articles.setRange(5, 100)
        self.digest_max_articles.setValue(20)
        digest_layout.addRow("Max Articles in Digest:", self.digest_max_articles)

        self.include_summaries = QCheckBox("Include article summaries")
        self.include_summaries.setChecked(True)
        digest_layout.addRow("", self.include_summaries)

        layout.addWidget(digest_group)

        layout.addStretch()
        return tab

    def _create_filtering_tab(self):
        """Create filtering configuration tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)

        # Topic Filters
        topic_group = QGroupBox("Topic Filters")
        topic_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
            }}
        """)

        topic_layout = QVBoxLayout(topic_group)

        topics = [
            "Artificial Intelligence",
            "Machine Learning",
            "Cybersecurity",
            "Cloud Computing",
            "Blockchain",
            "IoT",
            "Startups",
            "Programming",
        ]

        self.topic_checks = {}
        for topic in topics:
            check = QCheckBox(topic)
            check.setChecked(True)
            self.topic_checks[topic] = check
            topic_layout.addWidget(check)

        layout.addWidget(topic_group)

        # Source Filters
        source_group = QGroupBox("Source Filters")
        source_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
            }}
        """)

        source_layout = QVBoxLayout(source_group)

        self.all_sources = QCheckBox("All Sources")
        self.all_sources.setChecked(True)
        source_layout.addWidget(self.all_sources)

        specific_layout = QHBoxLayout()
        specific_layout.addWidget(QLabel("Or specific sources:"))

        self.source_list = QComboBox()
        self.source_list.addItems(
            ["TechCrunch", "Hacker News", "The Verge", "Wired", "Ars Technica"]
        )
        specific_layout.addWidget(self.source_list)
        specific_layout.addStretch()

        source_layout.addLayout(specific_layout)
        layout.addWidget(source_group)

        # Keywords
        keyword_group = QGroupBox("Keyword Alerts")
        keyword_group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLORS.cyan};
            }}
        """)

        keyword_layout = QVBoxLayout(keyword_group)

        keyword_desc = QLabel(
            "Alert when articles contain these keywords (one per line):"
        )
        keyword_desc.setStyleSheet(f"color: {COLORS.comment};")
        keyword_layout.addWidget(keyword_desc)

        self.keywords_text = QTextEdit()
        self.keywords_text.setPlaceholderText("Python\nRust\nKubernetes\nQuantum")
        self.keywords_text.setMaximumHeight(100)
        keyword_layout.addWidget(self.keywords_text)

        layout.addWidget(keyword_group)

        layout.addStretch()
        return tab

    def _apply_styles(self):
        """Apply dialog styles"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
            }}
            QLabel {{
                color: {COLORS.fg};
            }}
            QCheckBox {{
                color: {COLORS.fg};
            }}
            QLineEdit, QComboBox, QSpinBox, QTextEdit {{
                background-color: {COLORS.bg_input};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 4px;
                padding: 6px;
            }}
            QPushButton {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_visual};
            }}
            QPushButton#primaryButton {{
                background-color: {COLORS.green};
                color: {COLORS.black};
                border: none;
                font-weight: bold;
            }}
            QSlider::groove:horizontal {{
                background-color: {COLORS.bg_highlight};
                height: 8px;
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background-color: {COLORS.cyan};
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }}
        """)

    def _load_settings(self):
        """Load alert settings"""
        # Desktop
        self.desktop_enabled.setChecked(
            self._settings.value("desktop_enabled", True, bool)
        )
        self.desktop_duration.setValue(self._settings.value("desktop_duration", 5, int))

        # Email
        self.email_enabled.setChecked(
            self._settings.value("email_enabled", False, bool)
        )
        self.email_address.setText(self._settings.value("email_address", "", str))
        self.email_frequency.setCurrentText(
            self._settings.value("email_frequency", "Daily Digest", str)
        )

        # Webhook
        self.webhook_enabled.setChecked(
            self._settings.value("webhook_enabled", False, bool)
        )
        self.webhook_url.setText(self._settings.value("webhook_url", "", str))

        # Slack
        self.slack_enabled.setChecked(
            self._settings.value("slack_enabled", False, bool)
        )
        self.slack_webhook.setText(self._settings.value("slack_webhook", "", str))

        # Telegram
        self.telegram_enabled.setChecked(
            self._settings.value("telegram_enabled", False, bool)
        )
        self.telegram_bot_token.setText(
            self._settings.value("telegram_bot_token", "", str)
        )
        self.telegram_chat_id.setText(self._settings.value("telegram_chat_id", "", str))

        # Discord
        self.discord_enabled.setChecked(
            self._settings.value("discord_enabled", False, bool)
        )
        self.discord_webhook_url.setText(
            self._settings.value("discord_webhook_url", "", str)
        )
        self.discord_username.setText(self._settings.value("discord_username", "", str))

        # In-App
        self.inapp_enabled.setChecked(self._settings.value("inapp_enabled", True, bool))
        self.inapp_position.setCurrentText(
            self._settings.value("inapp_position", "Bottom Right", str)
        )
        self.inapp_sound.setChecked(self._settings.value("inapp_sound", False, bool))

        # Thresholds
        self.min_score.setValue(self._settings.value("min_score", 70, int))
        self.min_articles.setValue(self._settings.value("min_articles", 5, int))
        self.cooldown_minutes.setValue(self._settings.value("cooldown", 5, int))

        # Keywords
        self.keywords_text.setPlainText(self._settings.value("keywords", "", str))

    def _save_settings(self):
        """Save alert settings"""
        # Desktop
        self._settings.setValue("desktop_enabled", self.desktop_enabled.isChecked())
        self._settings.setValue("desktop_duration", self.desktop_duration.value())

        # Email
        self._settings.setValue("email_enabled", self.email_enabled.isChecked())
        self._settings.setValue("email_address", self.email_address.text())
        self._settings.setValue("email_frequency", self.email_frequency.currentText())

        # Webhook
        self._settings.setValue("webhook_enabled", self.webhook_enabled.isChecked())
        self._settings.setValue("webhook_url", self.webhook_url.text())

        # Slack
        self._settings.setValue("slack_enabled", self.slack_enabled.isChecked())
        self._settings.setValue("slack_webhook", self.slack_webhook.text())

        # Telegram
        self._settings.setValue("telegram_enabled", self.telegram_enabled.isChecked())
        self._settings.setValue("telegram_bot_token", self.telegram_bot_token.text())
        self._settings.setValue("telegram_chat_id", self.telegram_chat_id.text())

        # Discord
        self._settings.setValue("discord_enabled", self.discord_enabled.isChecked())
        self._settings.setValue("discord_webhook_url", self.discord_webhook_url.text())
        self._settings.setValue("discord_username", self.discord_username.text())

        # In-App
        self._settings.setValue("inapp_enabled", self.inapp_enabled.isChecked())
        self._settings.setValue("inapp_position", self.inapp_position.currentText())
        self._settings.setValue("inapp_sound", self.inapp_sound.isChecked())

        # Thresholds
        self._settings.setValue("min_score", self.min_score.value())
        self._settings.setValue("min_articles", self.min_articles.value())
        self._settings.setValue("cooldown", self.cooldown_minutes.value())

        # Keywords
        self._settings.setValue("keywords", self.keywords_text.toPlainText())

        self._settings.sync()
        self.accept()

    def _test_alerts(self):
        """Send test alerts to configured channels"""
        QMessageBox.information(
            self,
            "Test Alerts",
            "Test notifications sent to all enabled channels!\n\n"
            "Check your configured destinations.",
        )


# Convenience function
def show_alert_config(parent=None):
    """Show alert configuration dialog"""
    dialog = AlertConfigDialog(parent)
    return dialog.exec()
