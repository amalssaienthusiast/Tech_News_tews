"""
Sentiment Dashboard Dialog - PyQt6

Shows sentiment analysis of articles with charts and statistics.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QFrame,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTabWidget,
)

from gui_qt.theme import COLORS
from src.intelligence.sentiment_analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)


def _parse_published_at(value) -> Optional[datetime]:
    """Best-effort parse of an article's published_at field (ISO string, or already
    a datetime). Returns None if missing/unparseable so callers can exclude it."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError) as e:
        logger.debug(f"_parse_published_at: could not parse {value!r}: {e}")
        return None


class SentimentGauge(QFrame):
    """Visual gauge for sentiment score."""

    def __init__(self, title: str = "Sentiment", parent=None):
        super().__init__(parent)
        self.title = title
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 10px;
            }}
        """)

        layout = QVBoxLayout(self)

        # Title
        title_label = QLabel(self.title)
        title_label.setStyleSheet(f"color: {COLORS.fg}; font-weight: bold;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Score display
        self.score_label = QLabel("0.0")
        self.score_label.setStyleSheet(
            f"font-size: 32px; font-weight: bold; color: {COLORS.cyan};"
        )
        self.score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.score_label)

        # Progress bar
        self.bar = QProgressBar()
        self.bar.setRange(-100, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS.bg_dark};
                border: 1px solid {COLORS.border};
                border-radius: 4px;
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS.cyan};
            }}
        """)
        layout.addWidget(self.bar)

        # Label
        self.label = QLabel("Neutral")
        self.label.setStyleSheet(f"color: {COLORS.comment};")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

    def set_score(self, score: float):
        """Set sentiment score (-1.0 to 1.0)."""
        self.score_label.setText(f"{score:+.2f}")
        self.bar.setValue(int(score * 100))

        # Color based on sentiment
        if score > 0.2:
            color = COLORS.green
            label = "Positive"
        elif score < -0.2:
            color = COLORS.red
            label = "Negative"
        else:
            color = COLORS.yellow
            label = "Neutral"

        self.score_label.setStyleSheet(
            f"font-size: 32px; font-weight: bold; color: {color};"
        )
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS.bg_dark};
                border: 1px solid {COLORS.border};
                border-radius: 4px;
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
            }}
        """)
        self.label.setText(label)
        self.label.setStyleSheet(f"color: {color}; font-weight: bold;")


class SentimentDashboard(QDialog):
    """Sentiment analysis dashboard dialog."""

    def __init__(self, articles: List[Dict], parent=None):
        super().__init__(parent)
        self.articles = articles
        self.setWindowTitle("📊 Sentiment Dashboard")
        self.setMinimumSize(900, 700)
        self._setup_ui()
        self._analyze_sentiment()

    def _setup_ui(self):
        """Build the dashboard UI."""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
            }}
            QLabel {{
                color: {COLORS.fg};
            }}
            QTabWidget::pane {{
                background-color: {COLORS.bg};
                border: 1px solid {COLORS.border};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                padding: 10px 20px;
                border: 1px solid {COLORS.border};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS.cyan};
                color: {COLORS.black};
                font-weight: bold;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header
        header = QHBoxLayout()
        title = QLabel("📊 Sentiment Analysis Dashboard")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {COLORS.cyan};"
        )
        header.addWidget(title)
        header.addStretch()

        close_btn = QPushButton("✕ Close")
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.red};
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
            }}
        """)
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)

        layout.addLayout(header)

        # Overview gauges
        gauges_layout = QHBoxLayout()

        self.overall_gauge = SentimentGauge("Overall Sentiment")
        gauges_layout.addWidget(self.overall_gauge)

        self.recent_gauge = SentimentGauge("Recent (24h)")
        gauges_layout.addWidget(self.recent_gauge)

        self.trending_gauge = SentimentGauge("Trending")
        gauges_layout.addWidget(self.trending_gauge)

        layout.addLayout(gauges_layout)

        # Tabs
        self.tabs = QTabWidget()

        # Tab 1: Article List
        self.articles_table = QTableWidget()
        self.articles_table.setColumnCount(4)
        self.articles_table.setHorizontalHeaderLabels(
            ["Title", "Source", "Sentiment", "Score"]
        )
        self.articles_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.border};
                border-radius: 8px;
            }}
            QHeaderView::section {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                padding: 8px;
                border: none;
                font-weight: bold;
            }}
            QTableWidget::item {{
                padding: 6px;
            }}
        """)
        self.articles_table.horizontalHeader().setStretchLastSection(False)
        self.articles_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.articles_table.setAlternatingRowColors(True)
        self.tabs.addTab(self.articles_table, "📰 Articles")

        # Tab 2: Topics
        self.topics_widget = QWidget()
        topics_layout = QVBoxLayout(self.topics_widget)
        topics_label = QLabel("Topic sentiment analysis will appear here")
        topics_label.setStyleSheet(f"color: {COLORS.comment};")
        topics_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        topics_layout.addWidget(topics_label)
        self.tabs.addTab(self.topics_widget, "🏷️ Topics")

        # Tab 3: Sources
        self.sources_widget = QWidget()
        sources_layout = QVBoxLayout(self.sources_widget)
        sources_label = QLabel("Source sentiment analysis will appear here")
        sources_label.setStyleSheet(f"color: {COLORS.comment};")
        sources_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sources_layout.addWidget(sources_label)
        self.tabs.addTab(self.sources_widget, "🔗 Sources")

        layout.addWidget(self.tabs)

        # Summary
        self.summary_label = QLabel("Analyzing sentiment...")
        self.summary_label.setStyleSheet(f"color: {COLORS.comment}; padding: 10px;")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary_label)

    def _analyze_sentiment(self):
        """Analyze sentiment of articles."""
        if not self.articles:
            self.summary_label.setText("No articles to analyze")
            return
        
        # Calculate overall sentiment using actual SentimentAnalyzer
        sentiment_analyzer = SentimentAnalyzer()
        total_score = 0.0
        positive = 0
        negative = 0
        neutral = 0
        scored_articles = []  # (score, published_at | None), for recent/trending gauges
        
        self.articles_table.setRowCount(len(self.articles))
        
        for i, article in enumerate(self.articles):
            title = article.get("title", "")
            summary = article.get("summary", "") or article.get("content", "") or ""
            full_text = f"{title} {summary}"
            
            # Use real SentimentAnalyzer
            res = sentiment_analyzer.analyze_sentiment(full_text)
            label = res.get("label", "NEUTRAL")
            conf_score = res.get("score", 0.0)
            
            # Map NEUTRAL/POSITIVE/NEGATIVE + conf_score to a -1 to 1 score
            if label == "POSITIVE":
                score = conf_score
                positive += 1
            elif label == "NEGATIVE":
                score = -conf_score
                negative += 1
            else:
                score = 0.0
                neutral += 1
                
            total_score += score
            scored_articles.append((score, _parse_published_at(article.get("published_at"))))
            
            # Add to table
            self.articles_table.setItem(i, 0, QTableWidgetItem(title[:60]))
            self.articles_table.setItem(i, 1, QTableWidgetItem(article.get("source", "Unknown")))
            
            sentiment_text = label.capitalize()
            sentiment_item = QTableWidgetItem(sentiment_text)
            
            if label == "POSITIVE":
                sentiment_item.setForeground(Qt.GlobalColor.green)
            elif label == "NEGATIVE":
                sentiment_item.setForeground(Qt.GlobalColor.red)
            else:
                sentiment_item.setForeground(Qt.GlobalColor.yellow)
            
            self.articles_table.setItem(i, 2, sentiment_item)
            self.articles_table.setItem(i, 3, QTableWidgetItem(f"{score:+.2f}"))
        
        # Update gauges
        avg_score = total_score / len(self.articles) if self.articles else 0.0
        self.overall_gauge.set_score(avg_score)

        # Recent (24h): average sentiment among articles with a parseable published_at
        # in the last 24 hours. Falls back to the overall average when no article has
        # a usable timestamp, rather than showing a fabricated number.
        now = datetime.utcnow()
        recent = [s for s, dt in scored_articles if dt is not None and now - dt <= timedelta(hours=24)]
        recent_score = (sum(recent) / len(recent)) if recent else avg_score

        # Trending: sentiment momentum, i.e. average score of the most-recently-published
        # third of the set (min 1 article) vs. the overall set. Articles without a usable
        # timestamp are excluded from the "most recent" ranking so they can't skew it.
        dated = [(s, dt) for s, dt in scored_articles if dt is not None]
        if dated:
            dated.sort(key=lambda pair: pair[1], reverse=True)
            window = max(1, len(dated) // 3)
            trending_score = sum(s for s, _ in dated[:window]) / window
        else:
            trending_score = avg_score

        self.recent_gauge.set_score(recent_score)
        self.trending_gauge.set_score(trending_score)
        
        # Update summary
        self.summary_label.setText(
            f"Analyzed {len(self.articles)} articles: "
            f"{positive} positive, {negative} negative, {neutral} neutral"
        )
