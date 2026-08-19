"""
Full Article Content Viewer for Tech News Scraper
Displays complete article content with formatting and metadata.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS, Fonts

# Import real intelligence modules
from src.data_structures.trie import TechKeywordMatcher
from src.intelligence.sentiment_analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Disruptiveness keyword list
# ---------------------------------------------------------------------------
_DISRUPTIVE_KEYWORDS: List[str] = [
    "breach",
    "hack",
    "attack",
    "ban",
    "crisis",
    "collapse",
    "emergency",
    "shutdown",
    "recall",
    "lawsuit",
    "explosion",
    "war",
    "sanction",
    "fine",
    "regulation",
    "outage",
    "leaked",
    "arrested",
    "fraud",
    "bankruptcy",
]


def _compute_disruptive_score(text: str) -> int:
    """Return count of disruptive keyword hits in text (0–len(_DISRUPTIVE_KEYWORDS))."""
    lower = text.lower()
    return sum(1 for kw in _DISRUPTIVE_KEYWORDS if kw in lower)


# ---------------------------------------------------------------------------
# Hard Analyze tab
# ---------------------------------------------------------------------------


class _HardAnalyzeTab(QWidget):
    """
    On-demand deep NLP analysis tab.

    Displays:
      • Disruptiveness keyword hits + score
      • Sentiment (very simple positive/negative/neutral heuristic)
      • Named entities extracted with simple regex heuristics
      • Top keywords (by frequency)
      • AI Summary (if already stored on the article)
    """

    def __init__(
        self, article: Dict[str, Any], parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._article = article
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # ── Analyze button ───────────────────────────────────────────────
        self._analyze_btn = QPushButton("🧠 Hard Analyze")
        self._analyze_btn.setFixedHeight(42)
        self._analyze_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS.magenta};
                color: {COLORS.bg_dark};
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bright_magenta if hasattr(COLORS, "bright_magenta") else COLORS.magenta};
            }}
            QPushButton:disabled {{
                background-color: {COLORS.comment};
                color: {COLORS.bg_dark};
            }}
        """)
        self._analyze_btn.clicked.connect(self._run_analysis)
        layout.addWidget(self._analyze_btn)

        # ── Results area (hidden until analysis runs) ────────────────────
        self._results_widget = QWidget()
        results_layout = QVBoxLayout(self._results_widget)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(14)

        # Disruptiveness
        results_layout.addWidget(self._section_header("💥 Disruptiveness", COLORS.red))
        self._disruptive_label = QLabel("—")
        self._disruptive_label.setWordWrap(True)
        self._disruptive_label.setStyleSheet(
            f"color: {COLORS.fg}; padding: 8px; background: {COLORS.bg_dark}; border-radius: 6px;"
        )
        results_layout.addWidget(self._disruptive_label)

        # Sentiment
        results_layout.addWidget(self._section_header("💬 Sentiment", COLORS.yellow))
        self._sentiment_label = QLabel("—")
        self._sentiment_label.setStyleSheet(
            f"color: {COLORS.fg}; padding: 8px; background: {COLORS.bg_dark}; border-radius: 6px;"
        )
        results_layout.addWidget(self._sentiment_label)

        # Entities
        results_layout.addWidget(self._section_header("🏷️ Named Entities", COLORS.cyan))
        self._entities_text = QTextEdit()
        self._entities_text.setReadOnly(True)
        self._entities_text.setFixedHeight(100)
        self._entities_text.setStyleSheet(f"""
            QTextEdit {{
                background: {COLORS.bg_dark}; color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black}; border-radius: 6px; padding: 8px;
            }}
        """)
        results_layout.addWidget(self._entities_text)

        # Keywords
        results_layout.addWidget(self._section_header("🔑 Top Keywords", COLORS.blue))
        self._keywords_text = QTextEdit()
        self._keywords_text.setReadOnly(True)
        self._keywords_text.setFixedHeight(80)
        self._keywords_text.setStyleSheet(f"""
            QTextEdit {{
                background: {COLORS.bg_dark}; color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black}; border-radius: 6px; padding: 8px;
            }}
        """)
        results_layout.addWidget(self._keywords_text)

        # AI Summary
        results_layout.addWidget(self._section_header("🤖 AI Summary", COLORS.green))
        self._ai_summary_text = QTextEdit()
        self._ai_summary_text.setReadOnly(True)
        self._ai_summary_text.setMinimumHeight(100)
        self._ai_summary_text.setStyleSheet(f"""
            QTextEdit {{
                background: {COLORS.bg_dark}; color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black}; border-radius: 6px; padding: 8px;
                line-height: 1.5;
            }}
        """)
        results_layout.addWidget(self._ai_summary_text)

        results_layout.addStretch()

        self._results_widget.setVisible(False)
        layout.addWidget(self._results_widget)
        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _section_header(self, text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")
        return lbl

    def _run_analysis(self) -> None:
        """Run the analysis synchronously (CPU-only, no network)."""
        self._analyze_btn.setEnabled(False)
        self._analyze_btn.setText("⏳ Analyzing...")
        QTimer.singleShot(50, self._do_analysis)

    def _do_analysis(self) -> None:
        try:
            article = self._article
            title = article.get("title", "")
            summary = article.get("summary", "") or article.get("content", "") or ""
            full_text = f"{title} {summary}"

            # Initialize backend intelligence
            matcher = TechKeywordMatcher()
            sentiment_analyzer = SentimentAnalyzer()

            # ── Disruptiveness (Using TechKeywordMatcher) ───────────────────────────────────────────
            found = matcher.find_matches(full_text)
            matches = {kw: weight for kw, _pos, weight in found}
            score = round(sum(matches.values()))
            hits = sorted(matches.keys())

            if score == 0:
                disruptive_text = "Not disruptive (0 keyword hits)"
                disruptive_color = COLORS.comment
            elif score <= 2:
                disruptive_text = f"Mildly disruptive — {len(hits)} hit(s) [Score: {score}]: {', '.join(hits)}"
                disruptive_color = COLORS.yellow
            elif score <= 4:
                disruptive_text = (
                    f"Disruptive — {len(hits)} hits [Score: {score}]: {', '.join(hits)}"
                )
                disruptive_color = COLORS.orange
            else:
                disruptive_text = f"HIGHLY DISRUPTIVE — {len(hits)} hits [Score: {score}]: {', '.join(hits)}"
                disruptive_color = COLORS.red
            self._disruptive_label.setText(disruptive_text)
            self._disruptive_label.setStyleSheet(
                f"color: {disruptive_color}; padding: 8px; background: {COLORS.bg_dark}; border-radius: 6px; font-weight: bold;"
            )

            # ── Sentiment (Using real SentimentAnalyzer) ────────────────────
            # ── Sentiment (Using real SentimentAnalyzer) ────────────────────
            sentiment_res = sentiment_analyzer.analyze(full_text, persist=False)
            label_str = str(sentiment_res.label.value if hasattr(sentiment_res.label, "value") else sentiment_res.label).lower() if sentiment_res.label else "neutral"
            score = float(sentiment_res.score) if sentiment_res.score is not None else 0.0

            if "negative" in label_str:
                sentiment = f"Negative  (Score: {score:+.2f})"
                sentiment_color = COLORS.red
            elif "positive" in label_str:
                sentiment = f"Positive  (Score: {score:+.2f})"
                sentiment_color = COLORS.green
            else:
                sentiment = f"Neutral  (Score: {score:+.2f})"
                sentiment_color = COLORS.yellow

            self._sentiment_label.setText(sentiment)
            self._sentiment_label.setStyleSheet(
                f"color: {sentiment_color}; padding: 8px; background: {COLORS.bg_dark}; border-radius: 6px; font-weight: bold;"
            )

            # ── Named entities (regex heuristic: Title Case words) ───────
            existing_entities: List[str] = list(article.get("entities", []) or [])
            if not existing_entities:
                # Extract sequences of 2+ consecutive Title-Case tokens
                found = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", full_text)
                existing_entities = list(dict.fromkeys(found))[
                    :20
                ]  # deduplicate, cap 20
            self._entities_text.setPlainText(
                ", ".join(existing_entities) if existing_entities else "None detected"
            )

            # ── Top keywords (by frequency, min 4 chars, skip stop-words) ─
            existing_kws: List[str] = list(article.get("keywords", []) or [])
            if not existing_kws:
                stop = {
                    "the",
                    "and",
                    "for",
                    "that",
                    "with",
                    "this",
                    "from",
                    "have",
                    "are",
                    "will",
                    "has",
                    "was",
                    "been",
                    "its",
                    "not",
                    "but",
                    "they",
                    "their",
                    "said",
                    "about",
                    "into",
                }
                words = re.findall(r"\b[a-z]{4,}\b", full_text.lower())
                freq: Dict[str, int] = {}
                for w in words:
                    if w not in stop:
                        freq[w] = freq.get(w, 0) + 1
                existing_kws = [
                    w for w, _ in sorted(freq.items(), key=lambda x: -x[1])
                ][:15]
            self._keywords_text.setPlainText(
                ", ".join(existing_kws) if existing_kws else "None extracted"
            )

            # ── AI Summary ───────────────────────────────────────────────
            ai_summary = (
                article.get("ai_summary")
                or article.get("summary")
                or "(No AI summary available for this article)"
            )
            self._ai_summary_text.setPlainText(ai_summary)

        except Exception as exc:
            logger.warning("Hard analysis error: %s", exc)
            self._disruptive_label.setText(f"Analysis error: {exc}")
        finally:
            self._analyze_btn.setEnabled(True)
            self._analyze_btn.setText("🔄 Re-Analyze")
            self._results_widget.setVisible(True)


# ---------------------------------------------------------------------------
# ArticleContentViewer
# ---------------------------------------------------------------------------


class ArticleContentViewer(QDialog):
    """Full article content viewer dialog."""

    content_fetched_signal = pyqtSignal(dict)

    def __init__(self, parent=None, article: Optional[Dict[str, Any]] = None, orchestrator=None):
        super().__init__(parent)

        self.article: Dict[str, Any] = article or {}
        # Optional TechNewsOrchestrator — when provided, the viewer will
        # fetch full article content via DeepScraper (through the
        # AsyncBridge) if the article's `content` field is empty. This
        # is the common case for RSS articles, which only carry a
        # summary/description, not the full body.
        self._orchestrator = orchestrator

        self.setWindowTitle("📰 Article Viewer")
        self.setMinimumSize(920, 720)

        # Pre-declare metadata labels so Pylance knows they exist.
        self.published_label = QLabel("N/A")
        self.fetched_label = QLabel("N/A")
        self.source_meta_label = QLabel("N/A")
        self.id_label = QLabel("N/A")
        self.url_label = QLabel("N/A")
        self.author_label = QLabel("N/A")

        self.content_fetched_signal.connect(self._on_content_fetched)

        self._setup_ui()
        self._apply_styles()

        if article:
            self._populate_article(article)


    def _setup_ui(self):
        """Build the viewer UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # ── Header ───────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_highlight};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        header_layout = QVBoxLayout(header)

        self.title_label = QLabel("Loading...")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"""
            font-size: 22px;
            font-weight: bold;
            color: {COLORS.cyan};
        """)
        header_layout.addWidget(self.title_label)

        # Meta row
        meta_layout = QHBoxLayout()

        self.source_label = QLabel("📰 Unknown")
        self.source_label.setStyleSheet(
            f"color: {COLORS.fg_dark}; font-weight: bold; font-size: 14px;"
        )
        meta_layout.addWidget(self.source_label)

        self.reading_time_label = QLabel("⏱️ -- min read")
        self.reading_time_label.setStyleSheet(
            f"color: {COLORS.comment}; font-size: 13px; margin-left: 10px;"
        )
        meta_layout.addWidget(self.reading_time_label)

        meta_layout.addStretch()

        # Score badge
        score_frame = QFrame()
        score_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS.bg_visual};
                border-radius: 12px;
                border: 1px solid {COLORS.terminal_black};
            }}
        """)
        score_layout = QHBoxLayout(score_frame)
        score_layout.setContentsMargins(12, 6, 12, 6)

        self.score_label = QLabel("★ Tech Score: --")
        self.score_label.setStyleSheet(
            f"color: {COLORS.green}; font-weight: bold; font-size: 13px;"
        )
        score_layout.addWidget(self.score_label)

        meta_layout.addWidget(score_frame)

        header_layout.addLayout(meta_layout)
        layout.addWidget(header)

        # ── Tabs ─────────────────────────────────────────────────────────
        self.tabs = QTabWidget()

        content_tab = self._create_content_tab()
        self.tabs.addTab(content_tab, "📝 Content")

        meta_tab = self._create_metadata_tab()
        self.tabs.addTab(meta_tab, "📊 Metadata")

        keywords_tab = self._create_keywords_tab()
        self.tabs.addTab(keywords_tab, "🏷️ Keywords")

        # Hard Analyze tab — populated after article is set
        self._analyze_tab = _HardAnalyzeTab(self.article)
        self.tabs.addTab(self._analyze_tab, "🧠 Hard Analyze")

        layout.addWidget(self.tabs, 1)

        # ── Bottom actions ────────────────────────────────────────────────
        button_layout = QHBoxLayout()

        self.open_btn = QPushButton("🔗 Open Original")
        self.open_btn.clicked.connect(self._open_original)
        button_layout.addWidget(self.open_btn)

        button_layout.addStretch()

        copy_btn = QPushButton("📋 Copy Content")
        copy_btn.clicked.connect(self._copy_content)
        button_layout.addWidget(copy_btn)

        share_btn = QPushButton("📤 Share")
        share_btn.clicked.connect(self._share_article)
        button_layout.addWidget(share_btn)

        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.reject)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _create_content_tab(self):
        """Create the content tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)  # PyQt6: qualified enum

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)

        # Summary section
        summary_header = QLabel("📝 Summary")
        summary_header.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {COLORS.blue};
            margin-top: 10px;
        """)
        content_layout.addWidget(summary_header)

        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setFont(Fonts.get_qfont("md"))
        self.summary_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 15px;
                line-height: 1.6;
            }}
        """)
        self.summary_text.setMinimumHeight(200)
        content_layout.addWidget(self.summary_text)

        # Full content section
        content_header = QLabel("📄 Full Content")
        content_header.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {COLORS.blue};
            margin-top: 20px;
        """)
        content_layout.addWidget(content_header)

        self.content_text = QTextEdit()
        self.content_text.setReadOnly(True)
        self.content_text.setFont(Fonts.get_qfont("md"))
        self.content_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 15px;
                line-height: 1.6;
            }}
        """)
        self.content_text.setMinimumHeight(300)
        content_layout.addWidget(self.content_text)

        content_layout.addStretch()

        scroll.setWidget(content_widget)
        layout.addWidget(scroll)

        return tab

    def _create_metadata_tab(self):
        """Create the metadata tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)

        grid = QGridLayout()
        grid.setSpacing(15)

        def _row(i: int, header_text: str, value_label: QLabel) -> None:
            lbl = QLabel(header_text)
            lbl.setStyleSheet(f"color: {COLORS.comment}; font-weight: bold;")
            grid.addWidget(lbl, i, 0)
            value_label.setWordWrap(True)
            value_label.setStyleSheet(f"color: {COLORS.fg};")
            grid.addWidget(value_label, i, 1)

        # Re-use the pre-declared labels from __init__ so Pylance knows the types.
        _row(0, "Published:", self.published_label)
        _row(1, "Fetched:", self.fetched_label)
        _row(2, "Source:", self.source_meta_label)
        _row(3, "Article ID:", self.id_label)
        _row(4, "URL:", self.url_label)
        _row(5, "Author:", self.author_label)

        layout.addLayout(grid)
        layout.addStretch()

        return tab

    def _create_keywords_tab(self):
        """Create the keywords tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)

        # Keywords section
        kw_header = QLabel("🏷️ Keywords")
        kw_header.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {COLORS.magenta};
            margin-bottom: 10px;
        """)
        layout.addWidget(kw_header)

        self.keywords_container = QWidget()
        self.keywords_layout = QHBoxLayout(self.keywords_container)
        self.keywords_layout.setSpacing(8)
        self.keywords_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        layout.addWidget(self.keywords_container)

        # Categories section
        cat_header = QLabel("📂 Categories")
        cat_header.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {COLORS.yellow};
            margin-top: 20px;
            margin-bottom: 10px;
        """)
        layout.addWidget(cat_header)

        self.categories_container = QWidget()
        self.categories_layout = QHBoxLayout(self.categories_container)
        self.categories_layout.setSpacing(8)
        self.categories_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        layout.addWidget(self.categories_container)

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
            QPushButton {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 10px 20px;
            }}
            QPushButton:hover {{
                background-color: {COLORS.bg_visual};
            }}
            QTabWidget::pane {{
                border: 1px solid {COLORS.terminal_black};
                background-color: {COLORS.bg_dark};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg_dark};
                padding: 10px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.cyan};
            }}
        """)

    def _populate_article(self, article: Dict[str, Any]):
        """Populate viewer with article data"""
        # Title
        title = article.get("title", "Untitled Article")
        self.title_label.setText(title)
        self.setWindowTitle(f"📰 {title[:50]}..." if len(title) > 50 else f"📰 {title}")

        # Source
        source = article.get("source", "Unknown")
        self.source_label.setText(f"📰 {source}")

        # Score
        tech_score = article.get("tech_score", 0)
        if isinstance(tech_score, dict):
            tech_score = tech_score.get("score", 0)
        tech_score = float(tech_score) if tech_score else 0.0

        self.score_label.setText(f"★ Tech Score: {tech_score:.1f}")

        if tech_score >= 8:
            color = COLORS.green
        elif tech_score >= 5:
            color = COLORS.yellow
        else:
            color = COLORS.red
        self.score_label.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 13px;"
        )

        # Summary
        summary = article.get("summary", "") or article.get("content", "") or article.get("description", "")
        if summary:
            if "<" in summary and ">" in summary:
                from bs4 import BeautifulSoup
                summary = BeautifulSoup(summary, "html.parser").get_text(separator=" ", strip=True)
            self.summary_text.setHtml(
                f"<p style='line-height: 1.6; font-size: 14px;'>{summary}</p>"
            )
        else:
            self.summary_text.setHtml(
                "<p style='color: #565f89; font-style: italic;'>No summary available</p>"
            )


        # Full content & subheadlines
        content = article.get("full_content", "") or article.get("content", "") or article.get("full_text", "")
        url = article.get("url", "")
        headings = article.get("headings", [])

        if len(str(content).strip()) >= 300:
            self._render_full_content(content, headings=headings)
        else:
            if url and url.startswith(("http://", "https://")):
                self.content_text.setHtml(
                    f"<p style='color: {COLORS.cyan}; font-style: italic; font-size: 14px;'>"
                    "⚡ <b>Fetching full content & subheadlines live from source...</b></p>"
                )
                self._trigger_background_fetch(url)
            else:
                self.content_text.setHtml(
                    f"<p style='color: {COLORS.comment}; font-style: italic;'>"
                    "Full content not available. Click 'Open Original' to view on source website.</p>"
                )

        # Metadata
        published = article.get("published_at") or article.get("published_date")
        if published:
            published_str = (
                published.strftime("%Y-%m-%d %H:%M")
                if isinstance(published, datetime)
                else str(published)[:16]
            )
            self.published_label.setText(published_str)

        fetched = article.get("fetched_at") or article.get("scraped_at")
        if fetched:
            fetched_str = (
                fetched.strftime("%Y-%m-%d %H:%M")
                if isinstance(fetched, datetime)
                else str(fetched)[:16]
            )
            self.fetched_label.setText(fetched_str)

        self.source_meta_label.setText(source)

        article_id = article.get("article_id") or article.get("id") or "N/A"
        self.id_label.setText(str(article_id))

        url = article.get("url", "")
        self.url_label.setText(url[:80] + "..." if len(url) > 80 else url)
        self._article_url = url

        author = article.get("author") or article.get("byline") or "Unknown"
        self.author_label.setText(author)

        # Keywords / categories
        keywords = article.get("keywords", []) or []
        self._populate_tags(self.keywords_layout, keywords, COLORS.magenta)

        categories = article.get("categories", []) or []
        self._populate_tags(self.categories_layout, categories, COLORS.yellow)

        # Refresh the Hard Analyze tab with the real article
        self._analyze_tab._article = article

    def _trigger_background_fetch(self, target_url: str) -> None:
        async def do_fetch() -> Dict[str, Any]:
            import primp
            from bs4 import BeautifulSoup
            from src.engine.deep_scraper import ContentExtractor

            fetch_url = target_url
            if "news.google.com" in fetch_url:
                try:
                    from googlenewsdecoder import gnewsdecoder
                    decoded = gnewsdecoder(fetch_url)
                    if isinstance(decoded, dict) and decoded.get("status") and decoded.get("decoded_url"):
                        fetch_url = decoded["decoded_url"]
                except Exception as exc:
                    logger.debug("Google URL decode warning: %s", exc)

            try:
                client = primp.Client(impersonate="chrome_136", timeout=12)
                resp = client.get(fetch_url)
                html = resp.text
                
                soup = BeautifulSoup(html, "html.parser")
                headings = []
                for h in soup.find_all(["h2", "h3"]):
                    htext = h.get_text(strip=True)
                    if htext and len(htext) > 5 and htext not in headings:
                        headings.append(htext)
                        
                extracted = ContentExtractor.extract(html, fetch_url)

                content_text = extracted.get("content", "")
                summary_text = extracted.get("description", "")
                
                if not content_text or len(content_text) < 100:
                    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 40]
                    content_text = "\n\n".join(paragraphs)
                    
                return {
                    "content": content_text,
                    "summary": summary_text,
                    "headings": headings,
                    "author": extracted.get("author", ""),
                    "keywords": extracted.get("keywords", []),
                    "decoded_url": fetch_url
                }
            except Exception as exc:
                logger.warning("Deep fetch error for %s: %s", fetch_url, exc)
                return {"content": "", "summary": "", "headings": [], "decoded_url": fetch_url}

        from gui_qt.utils.async_bridge import AsyncWorker
        from PyQt6.QtCore import QThreadPool

        worker = AsyncWorker(
            do_fetch(),
            callback=lambda res: self.content_fetched_signal.emit(res),
            error_callback=lambda exc: logger.debug("Fetch error: %s", exc)
        )
        QThreadPool.globalInstance().start(worker)

    def _on_content_fetched(self, data: Dict[str, Any]) -> None:
        content = data.get("content", "")
        summary = data.get("summary", "")
        headings = data.get("headings", [])
        author = data.get("author", "")
        decoded_url = data.get("decoded_url", "")

        if decoded_url and hasattr(self, "url_label"):
            self.url_label.setText(decoded_url[:80] + "..." if len(decoded_url) > 80 else decoded_url)
            self._article_url = decoded_url

        if author and (not hasattr(self, "author_label") or self.author_label.text() in ("Unknown", "N/A", "")):
            self.author_label.setText(author)

        if summary and ("No summary" in self.summary_text.toPlainText() or len(self.summary_text.toPlainText()) < 30):
            if "<" in summary and ">" in summary:
                from bs4 import BeautifulSoup
                summary = BeautifulSoup(summary, "html.parser").get_text(separator=" ", strip=True)
            self.summary_text.setHtml(f"<p style='line-height: 1.6; font-size: 14px;'>{summary}</p>")

        if content:
            self.article["content"] = content
            self.article["full_content"] = content
            self.article["headings"] = headings
            self._render_full_content(content, headings=headings)
        else:
            self.content_text.setHtml(
                f"<p style='color: {COLORS.comment}; font-style: italic;'>"
                "Could not extract full content automatically. Click 'Open Original' to view on source website.</p>"
            )

    def _render_full_content(self, content: str, headings: Optional[List[str]] = None) -> None:
        word_count = len(str(content).split())
        reading_time = max(1, round(word_count / 200))
        self.reading_time_label.setText(f"⏱️ {reading_time} min read")

        tech_score = round(min(9.8, max(5.0, (word_count / 140.0) + (len(headings or []) * 0.7))), 1)
        self.score_label.setText(f"★ Tech Score: {tech_score:.1f}")
        color = COLORS.green if tech_score >= 8 else (COLORS.yellow if tech_score >= 5 else COLORS.red)
        self.score_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13px;")

        headings_html = ""
        if headings:
            h_items = "".join(f"<li style='margin-bottom: 4px;'>📌 <b>{h}</b></li>" for h in headings[:8])
            headings_html = (
                f"<div style='background-color: {COLORS.bg_visual}; border-left: 3px solid {COLORS.magenta}; "
                f"padding: 10px 14px; border-radius: 4px; margin-bottom: 15px;'>"
                f"<span style='color: {COLORS.magenta}; font-weight: bold;'>Key Subheadlines:</span>"
                f"<ul style='margin-top: 6px; padding-left: 18px; color: {COLORS.fg};'>{h_items}</ul></div>"
            )

        if "<p" in content or "<br" in content or "<div" in content:
            formatted = content
        else:
            paragraphs = str(content).split("\n\n")
            formatted = "".join(f"<p style='line-height: 1.6; margin-bottom: 12px;'>{p.strip()}</p>" for p in paragraphs if p.strip())

        self.content_text.setHtml(f"{headings_html}{formatted}")

    def _populate_tags(self, layout, tags, color):
        """Populate tags into layout"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not tags:
            empty_label = QLabel("None")
            empty_label.setStyleSheet(f"color: {COLORS.comment}; font-style: italic;")
            layout.addWidget(empty_label)
            return

        for tag in tags[:15]:
            tag_label = QLabel(f"  {tag}  ")
            tag_label.setStyleSheet(f"""
                background-color: {COLORS.bg_visual};
                color: {color};
                border-radius: 10px;
                padding: 4px 10px;
                font-size: {Fonts.get_size("sm")}px;
            """)
            layout.addWidget(tag_label)

        if len(tags) > 15:
            more_label = QLabel(f"+{len(tags) - 15} more")
            more_label.setStyleSheet(
                f"color: {COLORS.comment}; font-size: {Fonts.get_size('xs')}px;"
            )
            layout.addWidget(more_label)

        layout.addStretch()

    def _open_original(self):
        """Open original article in browser"""
        url = getattr(self, "_article_url", None)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _copy_content(self):
        """Copy article content to clipboard"""
        title = self.article.get("title", "")
        content = self.content_text.toPlainText()
        url = self.article.get("url", "")

        full_text = f"{title}\n\n{content}\n\nRead more: {url}"
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(full_text)  # type: ignore[union-attr]

        QMessageBox.information(self, "Copied", "Article content copied to clipboard!")

    def _share_article(self):
        """Copy share text to clipboard"""
        url = self.article.get("url", "")
        title = self.article.get("title", "")
        share_text = f"Check out this article: {title}\n\n{url}"
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(share_text)  # type: ignore[union-attr]

        QMessageBox.information(
            self,
            "Share",
            "Share text copied to clipboard!\n\nYou can paste it anywhere to share.",
        )

    def set_article(self, article: Dict[str, Any]):
        """Set article to display"""
        self.article = article
        self._populate_article(article)


def show_article_viewer(parent=None, article: Optional[Dict[str, Any]] = None, orchestrator=None):
    """Show article content viewer dialog. Always opens the popup (no browser fallback here).

    If `orchestrator` is provided (a TechNewsOrchestrator), the viewer will
    fetch full article content via DeepScraper on a background thread when
    the article's `content` field is empty (common for RSS articles).
    """
    dialog = ArticleContentViewer(parent, article, orchestrator=orchestrator)
    return dialog.exec()
