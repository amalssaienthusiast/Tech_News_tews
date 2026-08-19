"""
Newsletter Generator and History Dialog for Tech News Scraper
PyQt6 version with Tokyo Night theme

Features:
- Generator tab: Create newsletters from selected articles
- History tab: View and manage previously generated newsletters
- Export options: HTML, Markdown, Plain Text
- Multiple style options
- Tokyo Night theme styling
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QWidget, QTextEdit, QLineEdit, QListWidget,
    QListWidgetItem, QComboBox, QCheckBox, QProgressBar,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QSplitter, QFrame, QScrollArea, QFileDialog,
    QDateEdit, QSpinBox, QGridLayout, QStackedWidget, QMenu,
    QApplication, QToolButton, QStyledItemDelegate
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal as Signal, pyqtSlot as Slot, QDate, QThread, QSize,
    QPropertyAnimation, QEasingCurve, QPoint, QRect
)
from PyQt6.QtGui import (
    QColor, QTextCharFormat, QTextCursor, QFont, QIcon,
    QPainter, QBrush, QPen, QLinearGradient, QFontMetrics
)
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import asyncio
import threading

from ..theme import COLORS, Fonts, get_score_color


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class NewsletterHistoryEntry:
    """Represents a saved newsletter in history"""
    id: str
    date: str
    subject: str
    article_count: int
    format: str
    style: str
    file_path: Optional[str] = None
    created_at: Optional[str] = None
    preview: str = ""


@dataclass
class ArticleSelection:
    """Represents an article available for newsletter selection"""
    id: str
    title: str
    source: str
    url: str
    category: str
    tech_score: float
    summary: str
    selected: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# ANIMATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

class LoadingSpinner(QFrame):
    """Animated loading spinner for generation state"""
    
    def __init__(self, parent=None, size=40):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.start(16)  # ~60fps
        
    def _rotate(self):
        self._angle = (self._angle + 10) % 360
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw spinning arc
        rect = self.rect().adjusted(4, 4, -4, -4)
        pen = QPen(QColor(COLORS.cyan))
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        
        # Gradient arc
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(COLORS.cyan))
        gradient.setColorAt(0.5, QColor(COLORS.blue))
        gradient.setColorAt(1, QColor(COLORS.magenta))
        
        pen.setBrush(QBrush(gradient))
        painter.setPen(pen)
        
        # Draw arc
        painter.drawArc(rect, self._angle * 16, 240 * 16)


class AnimatedButton(QPushButton):
    """Button with hover animation"""
    
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._scale = 1.0
        self._animation = QPropertyAnimation(self, b"geometry")
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        
    def enterEvent(self, event):
        self.setStyleSheet(self.styleSheet() + f"""
            QPushButton {{
                background-color: {COLORS.bg_visual};
                transform: scale(1.02);
            }}
        """)
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        super().leaveEvent(event)


# ═══════════════════════════════════════════════════════════════════════════════
# GENERATOR TAB
# ═══════════════════════════════════════════════════════════════════════════════

class ArticleListItem(QWidget):
    """Custom widget for article list items with score indicator"""
    
    selection_changed = Signal(str, bool)  # article_id, selected
    
    def __init__(self, article: ArticleSelection, parent=None):
        super().__init__(parent)
        self.article = article
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        
        # Checkbox
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self.article.selected)
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        self.checkbox.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 20px;
                height: 20px;
                border-radius: 4px;
                border: 2px solid {COLORS.terminal_black};
                background-color: {COLORS.bg_highlight};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS.cyan};
                border-color: {COLORS.cyan};
            }}
        """)
        layout.addWidget(self.checkbox)
        
        # Score badge
        score_color = get_score_color(self.article.tech_score)
        score_label = QLabel(f"{self.article.tech_score:.1f}")
        score_label.setFixedSize(40, 24)
        score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        score_label.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS.bg_dark};
                color: {score_color};
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }}
        """)
        layout.addWidget(score_label)
        
        # Title and info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        
        title = QLabel(self.article.title[:60] + "..." if len(self.article.title) > 60 else self.article.title)
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS.fg};
                font-weight: 500;
            }}
        """)
        title.setToolTip(self.article.title)
        info_layout.addWidget(title)
        
        meta = QLabel(f"{self.article.source} • {self.article.category}")
        meta.setStyleSheet(f"color: {COLORS.comment}; font-size: 11px;")
        info_layout.addWidget(meta)
        
        layout.addLayout(info_layout, stretch=1)
        
        # Hover effect container
        self.setStyleSheet(f"""
            QWidget {{
                background-color: transparent;
                border-radius: 6px;
            }}
            QWidget:hover {{
                background-color: {COLORS.bg_visual};
            }}
        """)
        
    def _on_checkbox_changed(self, state):
        self.article.selected = state == Qt.Checked
        self.selection_changed.emit(self.article.id, self.article.selected)
        
    def mousePressEvent(self, event):
        self.checkbox.toggle()


class GeneratorTab(QWidget):
    """Newsletter generator tab with article selection and preview"""
    
    generate_requested = Signal(dict)  # Generation options
    export_requested = Signal(str, str)  # format, content
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._articles: List[ArticleSelection] = []
        self._generated_content = ""
        self._is_generating = False
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Left panel - Controls
        left_panel = self._create_left_panel()
        layout.addWidget(left_panel, stretch=1)
        
        # Right panel - Preview
        right_panel = self._create_right_panel()
        layout.addWidget(right_panel, stretch=1)
        
    def _create_left_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("cardFrame")
        panel.setStyleSheet(f"""
            QFrame#cardFrame {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 12px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Subject line
        subject_label = QLabel("📧 Subject Line")
        subject_label.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold; font-size: 14px;")
        layout.addWidget(subject_label)
        
        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText("Enter newsletter subject...")
        self.subject_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
                border: 2px solid {COLORS.terminal_black};
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS.cyan};
            }}
        """)
        layout.addWidget(self.subject_input)
        
        # Article selection
        articles_header = QHBoxLayout()
        articles_label = QLabel("📰 Select Articles")
        articles_label.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold; font-size: 14px;")
        articles_header.addWidget(articles_label)
        
        articles_header.addStretch()
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.setObjectName("ghostButton")
        select_all_btn.setFixedHeight(28)
        select_all_btn.clicked.connect(self._select_all_articles)
        articles_header.addWidget(select_all_btn)
        
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ghostButton")
        clear_btn.setFixedHeight(28)
        clear_btn.clicked.connect(self._clear_selection)
        articles_header.addWidget(clear_btn)
        
        layout.addLayout(articles_header)
        
        # Article list
        self.article_list = QListWidget()
        self.article_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS.bg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                padding: 4px;
            }}
            QListWidget::item {{
                background-color: transparent;
                border-radius: 6px;
                margin: 2px 0;
            }}
            QListWidget::item:hover {{
                background-color: {COLORS.bg_visual};
            }}
        """)
        self.article_list.setMaximumHeight(300)
        layout.addWidget(self.article_list)
        
        # Selected count
        self.selected_count_label = QLabel("0 articles selected")
        self.selected_count_label.setStyleSheet(f"color: {COLORS.comment}; font-size: 12px;")
        self.selected_count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.selected_count_label)
        
        # Options group
        options_group = QGroupBox("⚙️ Generation Options")
        options_group.setStyleSheet(self._groupbox_style(COLORS.blue))
        options_layout = QGridLayout(options_group)
        options_layout.setSpacing(12)
        
        # Format
        options_layout.addWidget(QLabel("Format:"), 0, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["HTML", "Markdown", "Plain Text"])
        self.format_combo.setCurrentText("HTML")
        self.format_combo.setStyleSheet(self._combobox_style())
        options_layout.addWidget(self.format_combo, 0, 1)
        
        # Style
        options_layout.addWidget(QLabel("Style:"), 1, 0)
        self.style_combo = QComboBox()
        self.style_combo.addItems(["Modern", "Classic", "Minimal"])
        self.style_combo.setCurrentText("Modern")
        self.style_combo.setStyleSheet(self._combobox_style())
        options_layout.addWidget(self.style_combo, 1, 1)
        
        # Checkboxes
        self.include_summaries_cb = QCheckBox("Include summaries")
        self.include_summaries_cb.setChecked(True)
        self.include_summaries_cb.setStyleSheet(self._checkbox_style())
        options_layout.addWidget(self.include_summaries_cb, 2, 0, 1, 2)
        
        self.include_scores_cb = QCheckBox("Include tech scores")
        self.include_scores_cb.setChecked(True)
        self.include_scores_cb.setStyleSheet(self._checkbox_style())
        options_layout.addWidget(self.include_scores_cb, 3, 0, 1, 2)
        
        self.group_by_category_cb = QCheckBox("Group by category")
        self.group_by_category_cb.setChecked(True)
        self.group_by_category_cb.setStyleSheet(self._checkbox_style())
        options_layout.addWidget(self.group_by_category_cb, 4, 0, 1, 2)
        
        layout.addWidget(options_group)
        
        # Generate button
        self.generate_btn = QPushButton("✨ Generate Newsletter")
        self.generate_btn.setObjectName("primaryButton")
        self.generate_btn.setFixedHeight(50)
        self.generate_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS.blue}, stop:1 {COLORS.cyan});
                color: {COLORS.black};
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS.bright_blue}, stop:1 {COLORS.bright_cyan});
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS.blue}, stop:1 {COLORS.blue});
            }}
            QPushButton:disabled {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.comment};
            }}
        """)
        self.generate_btn.clicked.connect(self._on_generate)
        layout.addWidget(self.generate_btn)
        
        # Loading spinner (hidden by default)
        self.spinner = LoadingSpinner(self, size=30)
        self.spinner.hide()
        
        layout.addStretch()
        
        return panel
        
    def _create_right_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("cardFrame")
        panel.setStyleSheet(f"""
            QFrame#cardFrame {{
                background-color: {COLORS.bg_highlight};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 12px;
            }}
        """)
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Preview header
        preview_header = QHBoxLayout()
        preview_label = QLabel("👁️ Preview")
        preview_label.setStyleSheet(f"color: {COLORS.cyan}; font-weight: bold; font-size: 14px;")
        preview_header.addWidget(preview_label)
        
        preview_header.addStretch()
        
        # View mode toggle
        self.view_stack = QStackedWidget()
        
        # Plain text view
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setPlaceholderText("Generated newsletter will appear here...")
        self.preview_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS.bg};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                padding: 12px;
                font-family: {Fonts.MONO};
            }}
        """)
        
        # HTML view
        self.preview_html = QTextEdit()
        self.preview_html.setReadOnly(True)
        self.preview_html.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS.bg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
            }}
        """)
        
        self.view_stack.addWidget(self.preview_text)
        self.view_stack.addWidget(self.preview_html)
        
        self.view_combo = QComboBox()
        self.view_combo.addItems(["Source", "Rendered"])
        self.view_combo.setCurrentText("Source")
        self.view_combo.setStyleSheet(self._combobox_style())
        self.view_combo.setFixedWidth(100)
        self.view_combo.currentTextChanged.connect(self._on_view_mode_changed)
        preview_header.addWidget(self.view_combo)
        
        layout.addLayout(preview_header)
        layout.addWidget(self.view_stack, stretch=1)
        
        # Export buttons
        export_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("💾 Save to File")
        self.save_btn.setObjectName("secondaryButton")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        export_layout.addWidget(self.save_btn)
        
        self.copy_btn = QPushButton("📋 Copy")
        self.copy_btn.setObjectName("cyanButton")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._on_copy)
        export_layout.addWidget(self.copy_btn)
        
        self.email_btn = QPushButton("📧 Send Email")
        self.email_btn.setObjectName("magentaButton")
        self.email_btn.setEnabled(False)
        self.email_btn.clicked.connect(self._on_send_email)
        export_layout.addWidget(self.email_btn)
        
        layout.addLayout(export_layout)
        
        return panel
        
    def _groupbox_style(self, color: str) -> str:
        return f"""
            QGroupBox {{
                background-color: {COLORS.bg_visual};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 8px;
                padding: 15px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 6px;
                color: {color};
            }}
        """
        
    def _combobox_style(self) -> str:
        return f"""
            QComboBox {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 6px 12px;
                min-width: 100px;
            }}
            QComboBox:hover {{
                border-color: {COLORS.comment};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid {COLORS.comment};
                margin-right: 8px;
            }}
        """
        
    def _checkbox_style(self) -> str:
        return f"""
            QCheckBox {{
                color: {COLORS.fg};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 1px solid {COLORS.terminal_black};
                background-color: {COLORS.bg_highlight};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS.blue};
                border: 1px solid {COLORS.blue};
            }}
        """
        
    def _on_view_mode_changed(self, mode: str):
        if mode == "Source":
            self.view_stack.setCurrentIndex(0)
        else:
            self.view_stack.setCurrentIndex(1)
            
    def set_articles(self, articles: List[Dict[str, Any]]):
        """Set available articles for selection"""
        self._articles = []
        self.article_list.clear()
        
        for article_data in articles:
            article = ArticleSelection(
                id=article_data.get('id', ''),
                title=article_data.get('title', 'Unknown'),
                source=article_data.get('source', 'Unknown'),
                url=article_data.get('url', ''),
                category=article_data.get('category', 'General'),
                tech_score=article_data.get('tech_score', 0.0),
                summary=article_data.get('summary', ''),
                selected=False
            )
            self._articles.append(article)
            
            # Create custom widget item
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 70))
            widget = ArticleListItem(article)
            widget.selection_changed.connect(self._on_article_selection_changed)
            self.article_list.addItem(item)
            self.article_list.setItemWidget(item, widget)
            
        self._update_selected_count()
        
    def _on_article_selection_changed(self, article_id: str, selected: bool):
        """Handle article selection change"""
        for article in self._articles:
            if article.id == article_id:
                article.selected = selected
                break
        self._update_selected_count()
        
    def _update_selected_count(self):
        """Update the selected articles count display"""
        count = sum(1 for a in self._articles if a.selected)
        self.selected_count_label.setText(f"{count} articles selected")
        
    def _select_all_articles(self):
        """Select all articles"""
        for i in range(self.article_list.count()):
            item = self.article_list.item(i)
            widget = self.article_list.itemWidget(item)
            if widget:
                widget.checkbox.setChecked(True)
                
    def _clear_selection(self):
        """Clear all selections"""
        for i in range(self.article_list.count()):
            item = self.article_list.item(i)
            widget = self.article_list.itemWidget(item)
            if widget:
                widget.checkbox.setChecked(False)
                
    def _on_generate(self):
        """Handle generate button click"""
        selected_articles = [a for a in self._articles if a.selected]
        
        if not selected_articles:
            QMessageBox.warning(self, "No Articles", "Please select at least one article.")
            return
            
        if not self.subject_input.text().strip():
            QMessageBox.warning(self, "No Subject", "Please enter a subject line.")
            return
            
        # Emit generation request
        options = {
            'subject': self.subject_input.text(),
            'articles': [asdict(a) for a in selected_articles],
            'format': self.format_combo.currentText(),
            'style': self.style_combo.currentText(),
            'include_summaries': self.include_summaries_cb.isChecked(),
            'include_scores': self.include_scores_cb.isChecked(),
            'group_by_category': self.group_by_category_cb.isChecked()
        }
        
        self._is_generating = True
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Generating...")
        
        # Show spinner
        self.spinner.show()
        self.spinner.move(
            self.generate_btn.x() + self.generate_btn.width() // 2 - 15,
            self.generate_btn.y() - 40
        )
        
        self.generate_requested.emit(options)
        
    def set_generated_content(self, content: str, format_type: str = "HTML"):
        """Set the generated newsletter content"""
        self._generated_content = content
        self._is_generating = False
        
        # Update preview
        self.preview_text.setPlainText(content)
        
        if format_type == "HTML":
            self.preview_html.setHtml(content)
        else:
            self.preview_html.setPlainText(content)
            
        # Enable buttons
        self.save_btn.setEnabled(True)
        self.copy_btn.setEnabled(True)
        self.email_btn.setEnabled(True)
        
        # Reset generate button
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("✨ Generate Newsletter")
        self.spinner.hide()
        
    def _on_save(self):
        """Save newsletter to file"""
        format_type = self.format_combo.currentText()
        
        if format_type == "HTML":
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save Newsletter", "newsletter.html", "HTML Files (*.html);;All Files (*)"
            )
        elif format_type == "Markdown":
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save Newsletter", "newsletter.md", "Markdown Files (*.md);;All Files (*)"
            )
        else:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save Newsletter", "newsletter.txt", "Text Files (*.txt);;All Files (*)"
            )
            
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self._generated_content)
                QMessageBox.information(self, "Saved", f"Newsletter saved to {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save: {str(e)}")
                
    def _on_copy(self):
        """Copy newsletter to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self._generated_content)
        
        # Show temporary success message
        self.copy_btn.setText("✓ Copied!")
        QTimer.singleShot(2000, lambda: self.copy_btn.setText("📋 Copy"))
        
    def _on_send_email(self):
        """Open email dialog"""
        QMessageBox.information(
            self, 
            "Send Email", 
            "Email sending feature will open your default email client.\n\n"
            "The newsletter content has been copied to your clipboard."
        )
        self._on_copy()


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORY TAB
# ═══════════════════════════════════════════════════════════════════════════════

class HistoryTab(QWidget):
    """Newsletter history management tab"""
    
    view_requested = Signal(str)  # newsletter_id
    export_requested = Signal(str, str)  # newsletter_id, format
    delete_requested = Signal(str)  # newsletter_id
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[NewsletterHistoryEntry] = []
        self._setup_ui()
        self._load_history()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header with search
        header = QHBoxLayout()
        
        title = QLabel("📚 Newsletter History")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS.cyan};
                font-weight: bold;
                font-size: 18px;
            }}
        """)
        header.addWidget(title)
        
        header.addStretch()
        
        # Search by date
        header.addWidget(QLabel("Filter by date:"))
        
        self.date_filter = QDateEdit()
        self.date_filter.setCalendarPopup(True)
        self.date_filter.setDate(QDate.currentDate())
        self.date_filter.setStyleSheet(self._date_edit_style())
        self.date_filter.dateChanged.connect(self._on_date_filter_changed)
        header.addWidget(self.date_filter)
        
        self.show_all_btn = QPushButton("Show All")
        self.show_all_btn.setObjectName("ghostButton")
        self.show_all_btn.clicked.connect(self._show_all)
        header.addWidget(self.show_all_btn)
        
        layout.addLayout(header)
        
        # Stats row
        stats_layout = QHBoxLayout()
        
        self.total_label = QLabel("Total: 0")
        self.total_label.setStyleSheet(f"color: {COLORS.comment};")
        stats_layout.addWidget(self.total_label)
        
        self.today_label = QLabel("Today: 0")
        self.today_label.setStyleSheet(f"color: {COLORS.green};")
        stats_layout.addWidget(self.today_label)
        
        self.this_week_label = QLabel("This week: 0")
        self.this_week_label.setStyleSheet(f"color: {COLORS.blue};")
        stats_layout.addWidget(self.this_week_label)
        
        stats_layout.addStretch()
        
        layout.addLayout(stats_layout)
        
        # History table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels([
            "Date", "Subject", "Articles", "Format", "Style", "Actions"
        ])
        self.history_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 8px;
                gridline-color: {COLORS.terminal_black};
            }}
            QTableWidget::item {{
                padding: 12px;
                border-bottom: 1px solid {COLORS.terminal_black};
            }}
            QTableWidget::item:selected {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
            }}
            QHeaderView::section {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.cyan};
                padding: 12px;
                border: none;
                border-right: 1px solid {COLORS.terminal_black};
                border-bottom: 2px solid {COLORS.cyan};
                font-weight: bold;
            }}
        """)
        
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Date
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Subject
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Articles
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Format
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Style
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Actions
        
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.history_table)
        
        # Bulk actions
        bulk_layout = QHBoxLayout()
        
        bulk_layout.addStretch()
        
        export_all_btn = QPushButton("📤 Export All")
        export_all_btn.setObjectName("secondaryButton")
        export_all_btn.clicked.connect(self._export_all)
        bulk_layout.addWidget(export_all_btn)
        
        delete_old_btn = QPushButton("🗑 Delete Old (>30 days)")
        delete_old_btn.setObjectName("ghostButton")
        delete_old_btn.clicked.connect(self._delete_old)
        bulk_layout.addWidget(delete_old_btn)
        
        layout.addLayout(bulk_layout)
        
    def _date_edit_style(self) -> str:
        return f"""
            QDateEdit {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QDateEdit::drop-down {{
                border: none;
                width: 24px;
            }}
            QCalendarWidget QWidget {{
                alternate-background-color: {COLORS.bg_highlight};
                background-color: {COLORS.bg};
                color: {COLORS.fg};
            }}
            QCalendarWidget QToolButton {{
                color: {COLORS.cyan};
                background-color: transparent;
            }}
            QCalendarWidget QMenu {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
            }}
        """
        
    def _load_history(self):
        """Load newsletter history from storage"""
        # Mock data for demonstration
        mock_entries = [
            NewsletterHistoryEntry(
                id="nl_001",
                date=datetime.now().strftime("%Y-%m-%d"),
                subject="Tech Daily: AI Breakthroughs and Cloud Innovations",
                article_count=8,
                format="HTML",
                style="Modern",
                created_at=datetime.now().isoformat(),
                preview="Today's top stories include..."
            ),
            NewsletterHistoryEntry(
                id="nl_002",
                date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                subject="Security Alert: Critical Vulnerabilities Patched",
                article_count=5,
                format="Markdown",
                style="Classic",
                created_at=(datetime.now() - timedelta(days=1)).isoformat(),
                preview="Critical security updates..."
            ),
            NewsletterHistoryEntry(
                id="nl_003",
                date=(datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
                subject="DevOps Weekly: CI/CD Trends and Best Practices",
                article_count=12,
                format="HTML",
                style="Minimal",
                created_at=(datetime.now() - timedelta(days=3)).isoformat(),
                preview="This week in DevOps..."
            ),
            NewsletterHistoryEntry(
                id="nl_004",
                date=(datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
                subject="Startup Spotlight: New Unicorns and Funding Rounds",
                article_count=6,
                format="Plain Text",
                style="Modern",
                created_at=(datetime.now() - timedelta(days=5)).isoformat(),
                preview="This week's startup news..."
            ),
            NewsletterHistoryEntry(
                id="nl_005",
                date=(datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                subject="AI & ML Digest: Latest Research and Tools",
                article_count=10,
                format="HTML",
                style="Modern",
                created_at=(datetime.now() - timedelta(days=7)).isoformat(),
                preview="Latest in AI/ML..."
            ),
        ]
        
        self._entries = mock_entries
        self._update_table()
        self._update_stats()
        
    def _update_table(self, entries: Optional[List[NewsletterHistoryEntry]] = None):
        """Update the history table with entries"""
        if entries is None:
            entries = self._entries
            
        self.history_table.setRowCount(0)
        
        for entry in entries:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            
            # Date
            date_item = QTableWidgetItem(entry.date)
            date_item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self.history_table.setItem(row, 0, date_item)
            
            # Subject
            subject_item = QTableWidgetItem(entry.subject[:50] + "..." if len(entry.subject) > 50 else entry.subject)
            subject_item.setToolTip(entry.subject)
            self.history_table.setItem(row, 1, subject_item)
            
            # Article count
            count_item = QTableWidgetItem(str(entry.article_count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.history_table.setItem(row, 2, count_item)
            
            # Format
            format_item = QTableWidgetItem(entry.format)
            format_colors = {
                "HTML": COLORS.magenta,
                "Markdown": COLORS.cyan,
                "Plain Text": COLORS.comment
            }
            format_item.setForeground(QColor(format_colors.get(entry.format, COLORS.fg)))
            self.history_table.setItem(row, 3, format_item)
            
            # Style
            style_item = QTableWidgetItem(entry.style)
            self.history_table.setItem(row, 4, style_item)
            
            # Actions
            actions_widget = self._create_actions_widget(entry)
            self.history_table.setCellWidget(row, 5, actions_widget)
            
    def _create_actions_widget(self, entry: NewsletterHistoryEntry) -> QWidget:
        """Create action buttons for a history entry"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        
        # View button
        view_btn = QToolButton()
        view_btn.setText("👁️")
        view_btn.setToolTip("View newsletter")
        view_btn.setStyleSheet(self._action_button_style(COLORS.blue))
        view_btn.clicked.connect(lambda: self.view_requested.emit(entry.id))
        layout.addWidget(view_btn)
        
        # Export button
        export_btn = QToolButton()
        export_btn.setText("📤")
        export_btn.setToolTip("Export")
        export_btn.setStyleSheet(self._action_button_style(COLORS.green))
        export_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        
        export_menu = QMenu(export_btn)
        export_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.fg};
                border: 1px solid {COLORS.terminal_black};
                border-radius: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px;
            }}
            QMenu::item:selected {{
                background-color: {COLORS.bg_visual};
            }}
        """)
        export_menu.addAction("Export as HTML", lambda: self.export_requested.emit(entry.id, "HTML"))
        export_menu.addAction("Export as Markdown", lambda: self.export_requested.emit(entry.id, "Markdown"))
        export_menu.addAction("Export as Text", lambda: self.export_requested.emit(entry.id, "Plain Text"))
        export_btn.setMenu(export_menu)
        layout.addWidget(export_btn)
        
        # Delete button
        delete_btn = QToolButton()
        delete_btn.setText("🗑️")
        delete_btn.setToolTip("Delete")
        delete_btn.setStyleSheet(self._action_button_style(COLORS.red))
        delete_btn.clicked.connect(lambda: self._confirm_delete(entry))
        layout.addWidget(delete_btn)
        
        return widget
        
    def _action_button_style(self, color: str) -> str:
        return f"""
            QToolButton {{
                background-color: {COLORS.bg_visual};
                color: {color};
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QToolButton:hover {{
                background-color: {color};
                color: {COLORS.black};
            }}
        """
        
    def _confirm_delete(self, entry: NewsletterHistoryEntry):
        """Show confirmation before deleting"""
        reply = QMessageBox.question(
            self,
            "Delete Newsletter",
            f"Delete newsletter from {entry.date}?\n\nSubject: {entry.subject}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.delete_requested.emit(entry.id)
            self._entries = [e for e in self._entries if e.id != entry.id]
            self._update_table()
            self._update_stats()
            
    def _on_date_filter_changed(self, date: QDate):
        """Filter history by selected date"""
        selected_date = date.toString("yyyy-MM-dd")
        filtered = [e for e in self._entries if e.date == selected_date]
        self._update_table(filtered)
        
    def _show_all(self):
        """Show all history entries"""
        self._update_table()
        
    def _update_stats(self):
        """Update statistics labels"""
        total = len(self._entries)
        today = sum(1 for e in self._entries if e.date == datetime.now().strftime("%Y-%m-%d"))
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        this_week = sum(1 for e in self._entries if e.date >= week_ago)
        
        self.total_label.setText(f"Total: {total}")
        self.today_label.setText(f"Today: {today}")
        self.this_week_label.setText(f"This week: {this_week}")
        
    def _export_all(self):
        """Export all newsletters"""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export All Newsletters",
            "newsletters_backup.json",
            "JSON Files (*.json)"
        )
        
        if filename:
            try:
                data = [asdict(e) for e in self._entries]
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, default=str)
                QMessageBox.information(self, "Exported", f"{len(self._entries)} newsletters exported")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Export failed: {str(e)}")
                
    def _delete_old(self):
        """Delete newsletters older than 30 days"""
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        old_count = sum(1 for e in self._entries if e.date < cutoff)
        
        if old_count == 0:
            QMessageBox.information(self, "No Old Newsletters", "No newsletters older than 30 days found.")
            return
            
        reply = QMessageBox.question(
            self,
            "Delete Old Newsletters",
            f"Delete {old_count} newsletters older than 30 days?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._entries = [e for e in self._entries if e.date >= cutoff]
            self._update_table()
            self._update_stats()
            QMessageBox.information(self, "Deleted", f"{old_count} old newsletters deleted")
            
    def add_entry(self, entry: NewsletterHistoryEntry):
        """Add a new entry to history"""
        self._entries.insert(0, entry)
        self._update_table()
        self._update_stats()


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class NewsletterDialog(QDialog):
    """
    Newsletter Generator and History Dialog
    
    A comprehensive dialog for generating newsletters from selected articles
    and managing newsletter history.
    
    Usage:
        dialog = NewsletterDialog(parent, articles=articles)
        dialog.show()
    """
    
    def __init__(self, parent=None, articles: Optional[List[Dict]] = None, 
                 orchestrator=None, db_handler=None):
        super().__init__(parent)
        
        self._orchestrator = orchestrator
        self._db_handler = db_handler
        self._articles = articles or []
        
        self._setup_window()
        self._setup_ui()
        self._apply_styles()
        
    def _setup_window(self):
        """Configure dialog window properties"""
        self.setWindowTitle("📧 Newsletter Studio")
        self.setMinimumSize(1100, 750)
        self.setMaximumSize(1400, 1000)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        
    def _setup_ui(self):
        """Build the complete UI"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header
        header = self._create_header()
        main_layout.addWidget(header)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background-color: {COLORS.bg};
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: {COLORS.bg_dark};
                color: {COLORS.comment};
                padding: 12px 24px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 4px;
                font-weight: 500;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.cyan};
                border-top: 2px solid {COLORS.cyan};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {COLORS.bg_visual};
                color: {COLORS.fg};
            }}
        """)
        
        # Create tabs
        self.generator_tab = GeneratorTab()
        self.generator_tab.set_articles(self._articles)
        self.generator_tab.generate_requested.connect(self._on_generate)
        
        self.history_tab = HistoryTab()
        self.history_tab.view_requested.connect(self._on_view_history)
        self.history_tab.export_requested.connect(self._on_export_history)
        self.history_tab.delete_requested.connect(self._on_delete_history)
        
        self.tab_widget.addTab(self.generator_tab, "✨ Generator")
        self.tab_widget.addTab(self.history_tab, "📚 History")
        
        main_layout.addWidget(self.tab_widget, stretch=1)
        
        # Footer
        footer = self._create_footer()
        main_layout.addWidget(footer)
        
    def _create_header(self) -> QFrame:
        """Create the header with title"""
        header = QFrame()
        header.setObjectName("headerFrame")
        header.setFixedHeight(80)
        header.setStyleSheet(f"""
            QFrame#headerFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS.bg_dark}, stop:1 {COLORS.bg});
                border-bottom: 1px solid {COLORS.terminal_black};
            }}
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 16, 24, 16)
        
        # Icon and title
        icon_label = QLabel("📧")
        icon_label.setStyleSheet(f"font-size: 32px;")
        layout.addWidget(icon_label)
        
        title_layout = QVBoxLayout()
        
        title = QLabel("NEWSLETTER STUDIO")
        title.setStyleSheet(f"""
            QLabel {{
                font-size: 20px;
                font-weight: bold;
                color: {COLORS.fg};
            }}
        """)
        title_layout.addWidget(title)
        
        subtitle = QLabel("Generate, manage, and export newsletters")
        subtitle.setStyleSheet(f"color: {COLORS.comment}; font-size: 12px;")
        title_layout.addWidget(subtitle)
        
        layout.addLayout(title_layout)
        layout.addStretch()
        
        # Version badge
        version = QLabel("v4.1")
        version.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS.bg_highlight};
                color: {COLORS.cyan};
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(version)
        
        return header
        
    def _create_footer(self) -> QFrame:
        """Create the footer with status and controls"""
        footer = QFrame()
        footer.setObjectName("footerFrame")
        footer.setFixedHeight(60)
        footer.setStyleSheet(f"""
            QFrame#footerFrame {{
                background-color: {COLORS.bg_dark};
                border-top: 1px solid {COLORS.terminal_black};
            }}
        """)
        
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 12, 20, 12)
        
        # Status
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"color: {COLORS.green};")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        # Close button
        close_btn = QPushButton("✕ Close")
        close_btn.setObjectName("dangerButton")
        close_btn.setFixedHeight(36)
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        return footer
        
    def _apply_styles(self):
        """Apply additional custom styles"""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS.bg};
            }}
        """)
        
    def _on_generate(self, options: dict):
        """Handle newsletter generation request"""
        self.status_label.setText("Generating...")
        self.status_label.setStyleSheet(f"color: {COLORS.yellow};")
        
        # Run generation in background thread
        thread = threading.Thread(target=self._generate_newsletter, args=(options,))
        thread.daemon = True
        thread.start()
        
    def _generate_newsletter(self, options: dict):
        """Generate newsletter content"""
        try:
            # Simulate generation (replace with actual generation logic)
            content = self._create_newsletter_content(options)
            
            # Update UI in main thread
            from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
            QMetaObject.invokeMethod(
                self,
                "_on_generation_complete",
                Qt.QueuedConnection,
                Q_ARG(str, content),
                Q_ARG(str, options['format'])
            )
            
        except Exception as e:
            QMetaObject.invokeMethod(
                self,
                "_on_generation_error",
                Qt.QueuedConnection,
                Q_ARG(str, str(e))
            )
            
    def _create_newsletter_content(self, options: dict) -> str:
        """Create newsletter content based on options"""
        format_type = options['format']
        style = options['style']
        subject = options['subject']
        articles = options['articles']
        
        if format_type == "HTML":
            return self._generate_html_newsletter(subject, articles, style, options)
        elif format_type == "Markdown":
            return self._generate_markdown_newsletter(subject, articles, options)
        else:
            return self._generate_plain_newsletter(subject, articles, options)
            
    def _generate_html_newsletter(self, subject: str, articles: List[dict], 
                                   style: str, options: dict) -> str:
        """Generate HTML newsletter"""
        # Style definitions
        styles = {
            "Modern": {
                "header_bg": "#7aa2f7",
                "accent": "#7dcfff",
                "font": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
            },
            "Classic": {
                "header_bg": "#bb9af7",
                "accent": "#c792ea",
                "font": "Georgia, 'Times New Roman', serif"
            },
            "Minimal": {
                "header_bg": "#1f2335",
                "accent": "#565f89",
                "font": "'SF Mono', Consolas, monospace"
            }
        }
        
        s = styles.get(style, styles["Modern"])
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{subject}</title>
    <style>
        body {{
            font-family: {s['font']};
            line-height: 1.6;
            color: #c0caf5;
            background-color: #1a1b26;
            margin: 0;
            padding: 0;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #24283b;
        }}
        .header {{
            background: linear-gradient(135deg, {s['header_bg']}, {s['accent']});
            color: #15161e;
            padding: 40px 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: bold;
        }}
        .header .date {{
            margin-top: 10px;
            font-size: 14px;
            opacity: 0.9;
        }}
        .content {{
            padding: 30px;
        }}
        .article {{
            margin-bottom: 30px;
            padding-bottom: 30px;
            border-bottom: 1px solid #3b4261;
        }}
        .article:last-child {{
            border-bottom: none;
        }}
        .article-title {{
            font-size: 20px;
            font-weight: bold;
            color: #7dcfff;
            margin-bottom: 8px;
        }}
        .article-meta {{
            font-size: 12px;
            color: #565f89;
            margin-bottom: 12px;
        }}
        .article-summary {{
            color: #a9b1d6;
        }}
        .article-link {{
            display: inline-block;
            margin-top: 12px;
            color: #7aa2f7;
            text-decoration: none;
            font-weight: 500;
        }}
        .score-badge {{
            display: inline-block;
            background-color: #1a1b26;
            color: #9ece6a;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 8px;
        }}
        .footer {{
            background-color: #16161e;
            padding: 20px 30px;
            text-align: center;
            font-size: 12px;
            color: #565f89;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{subject}</h1>
            <div class="date">{datetime.now().strftime("%B %d, %Y")}</div>
        </div>
        <div class="content">
"""
        
        for article in articles:
            score_html = f'<span class="score-badge">Score: {article["tech_score"]:.1f}</span>' if options.get('include_scores') else ''
            summary_html = f'<div class="article-summary">{article.get("summary", "")}</div>' if options.get('include_summaries') else ''
            
            html += f"""
            <div class="article">
                <div class="article-title">{article['title']}{score_html}</div>
                <div class="article-meta">{article['source']} • {article['category']}</div>
                {summary_html}
                <a href="{article['url']}" class="article-link">Read more →</a>
            </div>
"""
        
        html += f"""
        </div>
        <div class="footer">
            Generated by Tech News Scraper Newsletter Studio
        </div>
    </div>
</body>
</html>"""
        
        return html
        
    def _generate_markdown_newsletter(self, subject: str, articles: List[dict], 
                                     options: dict) -> str:
        """Generate Markdown newsletter"""
        md = f"# {subject}\n\n"
        md += f"*{datetime.now().strftime('%B %d, %Y')}*\n\n"
        md += "---\n\n"
        
        for article in articles:
            score_str = f" **(Score: {article['tech_score']:.1f})**" if options.get('include_scores') else ""
            md += f"## {article['title']}{score_str}\n\n"
            md += f"**Source:** {article['source']} | **Category:** {article['category']}\n\n"
            
            if options.get('include_summaries') and article.get('summary'):
                md += f"{article['summary']}\n\n"
                
            md += f"[Read full article]({article['url']})\n\n"
            md += "---\n\n"
            
        md += "*Generated by Tech News Scraper Newsletter Studio*"
        
        return md
        
    def _generate_plain_newsletter(self, subject: str, articles: List[dict], 
                                    options: dict) -> str:
        """Generate Plain Text newsletter"""
        text = f"{subject}\n"
        text += "=" * len(subject) + "\n\n"
        text += f"Date: {datetime.now().strftime('%B %d, %Y')}\n\n"
        
        for i, article in enumerate(articles, 1):
            text += f"\n{i}. {article['title']}\n"
            text += "-" * (len(article['title']) + 4) + "\n"
            text += f"   Source: {article['source']}\n"
            text += f"   Category: {article['category']}\n"
            
            if options.get('include_scores'):
                text += f"   Tech Score: {article['tech_score']:.1f}/10\n"
                
            if options.get('include_summaries') and article.get('summary'):
                text += f"\n   {article['summary']}\n"
                
            text += f"\n   URL: {article['url']}\n"
            
        text += "\n" + "=" * 50 + "\n"
        text += "Generated by Tech News Scraper Newsletter Studio\n"
        
        return text
        
    @Slot(str, str)
    def _on_generation_complete(self, content: str, format_type: str):
        """Handle successful generation"""
        self.generator_tab.set_generated_content(content, format_type)
        self.status_label.setText("Generation complete")
        self.status_label.setStyleSheet(f"color: {COLORS.green};")
        
        # Add to history
        entry = NewsletterHistoryEntry(
            id=f"nl_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            date=datetime.now().strftime("%Y-%m-%d"),
            subject=self.generator_tab.subject_input.text(),
            article_count=sum(1 for a in self.generator_tab._articles if a.selected),
            format=format_type,
            style=self.generator_tab.style_combo.currentText(),
            created_at=datetime.now().isoformat(),
            preview=content[:200] + "..."
        )
        self.history_tab.add_entry(entry)
        
        # Switch to history tab to show new entry
        self.tab_widget.setCurrentIndex(1)
        
    @Slot(str)
    def _on_generation_error(self, error: str):
        """Handle generation error"""
        self.generator_tab.set_generated_content(f"Error: {error}", "Plain Text")
        self.generator_tab.generate_btn.setEnabled(True)
        self.generator_tab.generate_btn.setText("✨ Generate Newsletter")
        self.generator_tab.spinner.hide()
        self.status_label.setText("Generation failed")
        self.status_label.setStyleSheet(f"color: {COLORS.red};")
        QMessageBox.critical(self, "Generation Error", error)
        
    def _on_view_history(self, newsletter_id: str):
        """View a historical newsletter"""
        entry = next((e for e in self.history_tab._entries if e.id == newsletter_id), None)
        if entry:
            QMessageBox.information(
                self,
                "Newsletter Preview",
                f"Subject: {entry.subject}\n\nDate: {entry.date}\n"
                f"Articles: {entry.article_count}\nFormat: {entry.format}\n\n"
                f"Preview:\n{entry.preview}"
            )
            
    def _on_export_history(self, newsletter_id: str, format_type: str):
        """Export a historical newsletter"""
        entry = next((e for e in self.history_tab._entries if e.id == newsletter_id), None)
        if entry:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                f"Export as {format_type}",
                f"newsletter_{entry.date}.{format_type.lower()}",
                f"{format_type} Files (*.{format_type.lower()})"
            )
            if filename:
                QMessageBox.information(self, "Exported", f"Newsletter exported to {filename}")
                
    def _on_delete_history(self, newsletter_id: str):
        """Delete a historical newsletter"""
        pass  # Handled in HistoryTab
        
    def closeEvent(self, event):
        """Handle dialog close"""
        # Check if generation is in progress
        if hasattr(self.generator_tab, '_is_generating') and self.generator_tab._is_generating:
            reply = QMessageBox.question(
                self,
                "Generation in Progress",
                "A newsletter generation is in progress. Close anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
                
        event.accept()


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def show_newsletter_dialog(parent=None, articles: Optional[List[Dict]] = None):
    """
    Show the newsletter dialog as a modal popup
    
    Args:
        parent: Parent widget
        articles: Optional list of articles to pre-populate
    """
    dialog = NewsletterDialog(parent, articles=articles)
    dialog.exec()
    return dialog
