"""
Article List Widget with Virtual Scrolling
Uses Qt Model/View pattern for high performance with 1000+ articles

Components:
- ArticleListModel: QAbstractListModel holding article data
- ArticleDelegate: Custom painting for article cards
- ArticleListView: QListView wrapper with signals
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QListView,
    QStyledItemDelegate,
    QStyle,
    QWidget,
    QVBoxLayout,
    QAbstractItemView,
)
from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
    QModelIndex,
    QAbstractListModel,
    QSize,
    QRect,
    QPoint,
)
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QFont,
    QFontMetrics,
    QPen,
    QBrush,
    QLinearGradient,
    QPainterPath,
)

from ..theme import COLORS, Fonts, get_score_color, get_tier_color, get_score_gradient


class ArticleListModel(QAbstractListModel):
    """Model for article list data

    Provides efficient data storage and retrieval for virtual scrolling.
    """

    # Custom roles
    ArticleDataRole = Qt.ItemDataRole.UserRole + 1
    TitleRole = Qt.ItemDataRole.UserRole + 2
    SourceRole = Qt.ItemDataRole.UserRole + 3
    ScoreRole = Qt.ItemDataRole.UserRole + 4
    TierRole = Qt.ItemDataRole.UserRole + 5
    FreshnessRole = Qt.ItemDataRole.UserRole + 6
    TimestampRole = Qt.ItemDataRole.UserRole + 7
    UrlRole = Qt.ItemDataRole.UserRole + 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._articles: List[Dict[str, Any]] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        """Return number of articles"""
        if parent.isValid():
            return 0
        return len(self._articles)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Return data for given index and role"""
        if not index.isValid() or not (0 <= index.row() < len(self._articles)):
            return None

        article = self._articles[index.row()]

        if role == Qt.ItemDataRole.DisplayRole or role == self.TitleRole:
            return article.get("title", "Untitled")

        elif role == self.ArticleDataRole:
            return article

        elif role == self.SourceRole:
            return article.get("source", "Unknown")

        elif role == self.ScoreRole:
            score = article.get("tech_score", 0)
            if isinstance(score, dict):
                score = score.get("score", 0)
            return float(score) if score else 0.0

        elif role == self.TierRole:
            score = article.get("tech_score", 0)
            if isinstance(score, dict):
                score = score.get("score", 0)
            score = float(score) if score else 0.0

            if score >= 8.5:
                return "S"
            elif score >= 7.0:
                return "A"
            elif score >= 5.0:
                return "B"
            else:
                return "C"

        elif role == self.FreshnessRole:
            published = article.get("published_date") or article.get("published")
            return self._calculate_freshness(published)

        elif role == self.TimestampRole:
            published = article.get("published_date") or article.get("published")
            if published:
                try:
                    if isinstance(published, str):
                        published = datetime.fromisoformat(
                            published.replace("Z", "+00:00")
                        )
                    return published.strftime("%b %d, %H:%M")
                except Exception:
                    return ""
            return ""

        elif role == self.UrlRole:
            return article.get("url", "")

        return None

    def _calculate_freshness(self, published_date) -> str:
        """Calculate freshness level"""
        if not published_date:
            return "archive"

        try:
            if isinstance(published_date, str):
                published_date = datetime.fromisoformat(
                    published_date.replace("Z", "+00:00")
                )

            now = (
                datetime.now(published_date.tzinfo)
                if published_date.tzinfo
                else datetime.now()
            )
            age = now - published_date

            if age < timedelta(hours=1):
                return "breaking"
            elif age < timedelta(hours=6):
                return "fresh"
            elif age < timedelta(hours=24):
                return "recent"
            else:
                return "archive"
        except Exception:
            return "archive"

    # Public API for data manipulation
    def set_articles(self, articles: List[Dict[str, Any]]):
        """Replace all articles"""
        self.beginResetModel()
        self._articles = list(articles)
        self.endResetModel()

    def add_article(self, article: Dict[str, Any], prepend: bool = True):
        """Add a single article"""
        if prepend:
            self.beginInsertRows(QModelIndex(), 0, 0)
            self._articles.insert(0, article)
        else:
            row = len(self._articles)
            self.beginInsertRows(QModelIndex(), row, row)
            self._articles.append(article)
        self.endInsertRows()

    def add_articles(self, articles: List[Dict[str, Any]], prepend: bool = True):
        """Add multiple articles efficiently"""
        if not articles:
            return

        if prepend:
            self.beginInsertRows(QModelIndex(), 0, len(articles) - 1)
            self._articles = list(articles) + self._articles
        else:
            start = len(self._articles)
            self.beginInsertRows(QModelIndex(), start, start + len(articles) - 1)
            self._articles.extend(articles)
        self.endInsertRows()

    def clear(self):
        """Remove all articles"""
        self.beginResetModel()
        self._articles.clear()
        self.endResetModel()

    def get_article(self, index: int) -> Optional[Dict[str, Any]]:
        """Get article at index"""
        if 0 <= index < len(self._articles):
            return self._articles[index]
        return None

    def get_all_articles(self) -> List[Dict[str, Any]]:
        """Get all articles"""
        return self._articles.copy()

    def count(self) -> int:
        """Get article count"""
        return len(self._articles)


class ArticleDelegate(QStyledItemDelegate):
    """Custom delegate for painting article cards in list view"""

    CARD_HEIGHT = 90
    CARD_MARGIN = 8
    CARD_PADDING = 12
    SCORE_BAR_HEIGHT = 6
    TIER_BADGE_SIZE = 22

    FRESHNESS_EMOJI = {
        "breaking": "🔥",
        "fresh": "🆕",
        "recent": "📅",
        "archive": "📚",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fonts = {
            "title": Fonts.get_qfont("md", "bold"),
            "source": Fonts.get_qfont("sm"),
            "score": Fonts.get_qfont("sm", "bold"),
            "time": Fonts.get_qfont("xs"),
            "tier": Fonts.get_qfont("xs", "bold"),
        }

    def sizeHint(self, option, index) -> QSize:
        """Return size for each item"""
        return QSize(
            option.rect.width() - self.CARD_MARGIN * 2,
            self.CARD_HEIGHT + self.CARD_MARGIN,
        )

    def paint(self, painter: QPainter, option, index: QModelIndex):
        """Paint the article card"""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get data
        model = index.model()
        title = model.data(index, ArticleListModel.TitleRole)
        source = model.data(index, ArticleListModel.SourceRole)
        score = model.data(index, ArticleListModel.ScoreRole)
        tier = model.data(index, ArticleListModel.TierRole)
        freshness = model.data(index, ArticleListModel.FreshnessRole)
        timestamp = model.data(index, ArticleListModel.TimestampRole)

        # Calculate card rect with margins
        card_rect = option.rect.adjusted(
            self.CARD_MARGIN,
            self.CARD_MARGIN // 2,
            -self.CARD_MARGIN,
            -self.CARD_MARGIN // 2,
        )

        # Determine colors based on state
        is_selected = option.state & QStyle.State_Selected
        is_hovered = option.state & QStyle.State_MouseOver

        if is_selected:
            bg_color = QColor(COLORS.bg_visual)
            border_color = QColor(COLORS.blue)
        elif is_hovered:
            bg_color = QColor(COLORS.bg_visual)
            border_color = QColor(COLORS.terminal_black)
        else:
            bg_color = QColor(COLORS.bg_highlight)
            border_color = QColor(COLORS.terminal_black)

        # Draw card background
        path = QPainterPath()
        path.addRoundedRect(
            card_rect.x(), card_rect.y(), card_rect.width(), card_rect.height(), 8, 8
        )

        painter.fillPath(path, QBrush(bg_color))
        painter.setPen(QPen(border_color, 1))
        painter.drawPath(path)

        # Content area
        content_rect = card_rect.adjusted(
            self.CARD_PADDING, self.CARD_PADDING, -self.CARD_PADDING, -self.CARD_PADDING
        )

        # Draw tier badge (top right)
        tier_rect = QRect(
            content_rect.right() - self.TIER_BADGE_SIZE,
            content_rect.top(),
            self.TIER_BADGE_SIZE,
            self.TIER_BADGE_SIZE,
        )
        tier_color = QColor(get_tier_color(tier))

        tier_path = QPainterPath()
        tier_path.addRoundedRect(
            tier_rect.x(), tier_rect.y(), tier_rect.width(), tier_rect.height(), 4, 4
        )
        painter.fillPath(tier_path, QBrush(tier_color))

        painter.setFont(self._fonts["tier"])
        painter.setPen(QColor(COLORS.black))
        painter.drawText(tier_rect, Qt.AlignmentFlag.AlignCenter, tier)

        # Draw title (with ellipsis if too long)
        title_rect = QRect(
            content_rect.left(),
            content_rect.top(),
            content_rect.width() - self.TIER_BADGE_SIZE - 8,
            30,
        )
        painter.setFont(self._fonts["title"])
        painter.setPen(QColor(COLORS.fg))

        metrics = QFontMetrics(self._fonts["title"])
        elided_title = metrics.elidedText(
            title or "", Qt.TextElideMode.ElideRight, title_rect.width()
        )
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_title,
        )

        # Draw score bar
        score_bar_y = content_rect.top() + 36
        score_bar_width = content_rect.width() - 50
        score_bar_rect = QRect(
            content_rect.left(),
            score_bar_y,
            int(score_bar_width * (score / 10.0)),
            self.SCORE_BAR_HEIGHT,
        )

        # Score bar background
        bg_bar_rect = QRect(
            content_rect.left(), score_bar_y, score_bar_width, self.SCORE_BAR_HEIGHT
        )

        bg_path = QPainterPath()
        bg_path.addRoundedRect(
            bg_bar_rect.x(),
            bg_bar_rect.y(),
            bg_bar_rect.width(),
            bg_bar_rect.height(),
            3,
            3,
        )
        painter.fillPath(bg_path, QBrush(QColor(COLORS.bg_dark)))

        # Score bar fill with gradient
        if score > 0:
            color1, color2 = get_score_gradient(score)
            gradient = QLinearGradient(
                score_bar_rect.topLeft(), score_bar_rect.topRight()
            )
            gradient.setColorAt(0, QColor(color1))
            gradient.setColorAt(1, QColor(color2))

            fill_path = QPainterPath()
            fill_path.addRoundedRect(
                score_bar_rect.x(),
                score_bar_rect.y(),
                score_bar_rect.width(),
                score_bar_rect.height(),
                3,
                3,
            )
            painter.fillPath(fill_path, QBrush(gradient))

        # Score text
        score_text_rect = QRect(
            content_rect.right() - 40, score_bar_y - 2, 40, self.SCORE_BAR_HEIGHT + 4
        )
        painter.setFont(self._fonts["score"])
        painter.setPen(QColor(get_score_color(score)))
        painter.drawText(
            score_text_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{score:.1f}",
        )

        # Bottom row: freshness, source, timestamp
        bottom_y = content_rect.bottom() - 16

        # Freshness emoji
        freshness_emoji = self.FRESHNESS_EMOJI.get(freshness, "📚")
        painter.setFont(self._fonts["source"])
        painter.setPen(QColor(COLORS.fg_dark))
        painter.drawText(content_rect.left(), bottom_y + 12, freshness_emoji)

        # Source
        source_text = f"📰 {source}"
        source_x = content_rect.left() + 24
        painter.drawText(source_x, bottom_y + 12, source_text)

        # Timestamp (right aligned)
        painter.setFont(self._fonts["time"])
        painter.setPen(QColor(COLORS.comment))
        painter.drawText(
            QRect(content_rect.right() - 100, bottom_y, 100, 16),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            timestamp or "",
        )

        painter.restore()


class ArticleListView(QListView):
    """Custom list view for articles with virtual scrolling

    Signals:
        article_clicked(dict): Emitted when article is clicked
        article_double_clicked(dict): Emitted on double-click (open URL)
    """

    article_clicked = pyqtSignal(dict)
    article_double_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Create model and delegate
        self._model = ArticleListModel(self)
        self._delegate = ArticleDelegate(self)

        self.setModel(self._model)
        self.setItemDelegate(self._delegate)

        # Configure view for performance
        self._configure_view()

        # Connect signals
        self.clicked.connect(self._on_clicked)
        self.doubleClicked.connect(self._on_double_clicked)

    def _configure_view(self):
        """Configure view settings for optimal performance"""
        # Visual settings
        self.setStyleSheet(f"""
            QListView {{
                background-color: {COLORS.bg};
                border: none;
                outline: none;
            }}
            QListView::item {{
                padding: 0px;
            }}
        """)

        # Performance settings
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setMouseTracking(True)  # For hover effects

        # Uniform item sizes for better performance
        self.setUniformItemSizes(True)

        # Enable smooth scrolling
        self.verticalScrollBar().setSingleStep(20)

    def _on_clicked(self, index: QModelIndex):
        """Handle item click"""
        article = self._model.data(index, ArticleListModel.ArticleDataRole)
        if article:
            self.article_clicked.emit(article)

    def _on_double_clicked(self, index: QModelIndex):
        """Handle item double-click"""
        article = self._model.data(index, ArticleListModel.ArticleDataRole)
        if article:
            self.article_double_clicked.emit(article)

    # Public API
    def set_articles(self, articles: List[Dict[str, Any]]):
        """Set articles in the list"""
        self._model.set_articles(articles)

    def add_article(self, article: Dict[str, Any], prepend: bool = True):
        """Add a single article"""
        self._model.add_article(article, prepend)
        if prepend:
            self.scrollToTop()

    def add_articles(self, articles: List[Dict[str, Any]], prepend: bool = True):
        """Add multiple articles"""
        self._model.add_articles(articles, prepend)

    def clear(self):
        """Clear all articles"""
        self._model.clear()

    def get_model(self) -> ArticleListModel:
        """Get the underlying model"""
        return self._model

    def count(self) -> int:
        """Get article count"""
        return self._model.count()

    def scroll_to_top(self):
        """Scroll to top of list"""
        self.scrollToTop()

    def scroll_to_bottom(self):
        """Scroll to bottom of list"""
        self.scrollToBottom()
