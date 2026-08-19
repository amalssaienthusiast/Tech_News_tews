"""
GUI Qt Tests - Basic verification of PyQt6 components
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestImports:
    """Test that all components can be imported"""
    
    def test_pyside6_available(self):
        """PyQt6 should be installed"""
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
        assert QApplication is not None
    
    def test_theme_imports(self):
        """Theme module should import correctly"""
        from gui_qt.theme import COLORS, Fonts, TOKYO_NIGHT_QSS, apply_theme
        
        assert COLORS.cyan == "#7dcfff"
        assert COLORS.bg == "#1a1b26"
        assert Fonts.get_size('md') == 13
        assert len(TOKYO_NIGHT_QSS) > 100
    
    def test_widget_imports(self):
        """All widgets should import correctly"""
        from gui_qt.widgets import (
            SearchBar, ArticleCard, ArticleListView,
            StatsPanel, LoadingSpinner, WelcomeScreen,
            LiveFeedContainer
        )
        
        assert SearchBar is not None
        assert ArticleCard is not None
        assert ArticleListView is not None
        assert StatsPanel is not None
        assert LoadingSpinner is not None
        assert WelcomeScreen is not None
        assert LiveFeedContainer is not None
    
    def test_main_window_import(self):
        """MainWindow should import correctly"""
        from gui_qt.main_window import (
            TechNewsMainWindow, HeaderBar, Sidebar,
            TickerBar, DynamicStatusBar
        )
        
        assert TechNewsMainWindow is not None
        assert HeaderBar is not None
        assert Sidebar is not None
        assert TickerBar is not None
        assert DynamicStatusBar is not None
    
    def test_controller_import(self):
        """Controller should import correctly"""
        from gui_qt.controller import (
            TechNewsController, AsyncWorker, StreamWorker
        )
        
        assert TechNewsController is not None
        assert AsyncWorker is not None
        assert StreamWorker is not None
    
    def test_package_import(self):
        """Package-level imports should work"""
        from gui_qt import (
            TechNewsMainWindow, TechNewsController,
            apply_theme, COLORS
        )
        
        assert TechNewsMainWindow is not None
        assert TechNewsController is not None
        assert apply_theme is not None


class TestTheme:
    """Test theme functionality"""
    
    def test_colors_dataclass(self):
        """Colors dataclass should have all required colors"""
        from gui_qt.theme import COLORS
        
        required_colors = [
            'bg', 'bg_dark', 'bg_highlight', 'bg_visual',
            'fg', 'fg_dark',
            'cyan', 'blue', 'green', 'yellow', 'orange', 'red',
            'magenta', 'purple', 'comment', 'black'
        ]
        
        for color in required_colors:
            assert hasattr(COLORS, color), f"Missing color: {color}"
            value = getattr(COLORS, color)
            assert value.startswith('#'), f"Invalid color format: {color}={value}"
    
    def test_font_sizes(self):
        """Font sizes should be defined"""
        from gui_qt.theme import Fonts
        
        sizes = ['xs', 'sm', 'md', 'lg', 'xl', '2xl', '3xl', '4xl']
        
        for size in sizes:
            value = Fonts.get_size(size)
            assert isinstance(value, int), f"Invalid size: {size}"
            assert value > 0, f"Size too small: {size}={value}"
    
    def test_qss_contains_essential_styles(self):
        """QSS should contain essential styles"""
        from gui_qt.theme import TOKYO_NIGHT_QSS
        
        essential = [
            'QMainWindow',
            'QPushButton',
            'QLineEdit',
            'QLabel',
            'QScrollBar',
            'QProgressBar',
            'QStatusBar',
        ]
        
        for element in essential:
            assert element in TOKYO_NIGHT_QSS, f"Missing style for: {element}"


class TestUtilityFunctions:
    """Test theme utility functions"""
    
    def test_get_score_color(self):
        """Score color function should return appropriate colors"""
        from gui_qt.theme import get_score_color, COLORS
        
        assert get_score_color(9.0) == COLORS.green
        assert get_score_color(7.0) == COLORS.cyan
        assert get_score_color(5.5) == COLORS.yellow
        assert get_score_color(3.0) == COLORS.red
    
    def test_get_tier_color(self):
        """Tier color function should return appropriate colors"""
        from gui_qt.theme import get_tier_color, COLORS
        
        assert get_tier_color("S") == COLORS.magenta
        assert get_tier_color("A") == COLORS.green
        assert get_tier_color("B") == COLORS.blue
        assert get_tier_color("C") == COLORS.comment
    
    def test_get_score_gradient(self):
        """Score gradient should return tuple of colors"""
        from gui_qt.theme import get_score_gradient
        
        result = get_score_gradient(8.5)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(c.startswith('#') for c in result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
