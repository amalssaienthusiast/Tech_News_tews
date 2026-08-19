"""
Search History Manager for Tech News Scraper
Stores and manages search history with persistence
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal, QSettings


class SearchHistoryManager(QObject):
    """Manages search history with persistence
    
    Signals:
        history_updated(): Emitted when history changes
    """
    
    history_updated = pyqtSignal()
    
    MAX_HISTORY = 50  # Maximum entries to store
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("TechNewsScraper", "SearchHistory")
        self._history: List[Dict[str, Any]] = []
        self._load_history()
    
    def _load_history(self):
        """Load history from settings"""
        try:
            import json
            history_json = self._settings.value("history", "[]")
            if history_json:
                self._history = json.loads(history_json)
        except Exception as e:
            print(f"Error loading search history: {e}")
            self._history = []
    
    def _save_history(self):
        """Save history to settings"""
        try:
            import json
            history_json = json.dumps(self._history[-self.MAX_HISTORY:])
            self._settings.setValue("history", history_json)
            self._settings.sync()
        except Exception as e:
            print(f"Error saving search history: {e}")
    
    def add_search(self, query: str, results_count: int = 0):
        """Add a search to history
        
        Args:
            query: Search query string
            results_count: Number of results found
        """
        if not query or not query.strip():
            return
        
        query = query.strip()
        
        # Check if query already exists (remove old entry)
        self._history = [h for h in self._history if h.get("query") != query]
        
        # Add new entry at beginning
        entry = {
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "results_count": results_count
        }
        self._history.insert(0, entry)
        
        # Trim to max
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[:self.MAX_HISTORY]
        
        self._save_history()
        self.history_updated.emit()
    
    def get_history(self) -> List[Dict[str, Any]]:
        """Get all search history entries"""
        return self._history.copy()
    
    def get_recent(self, count: int = 10) -> List[str]:
        """Get recent search queries as strings"""
        return [h["query"] for h in self._history[:count]]
    
    def clear_history(self):
        """Clear all search history"""
        self._history.clear()
        self._save_history()
        self.history_updated.emit()
    
    def remove_entry(self, query: str):
        """Remove a specific entry"""
        self._history = [h for h in self._history if h.get("query") != query]
        self._save_history()
        self.history_updated.emit()
    
    def get_suggestions(self, partial: str, max_suggestions: int = 5) -> List[str]:
        """Get search suggestions based on partial input"""
        if not partial:
            return self.get_recent(max_suggestions)
        
        partial_lower = partial.lower()
        suggestions = []
        
        for entry in self._history:
            query = entry["query"]
            if partial_lower in query.lower() and query not in suggestions:
                suggestions.append(query)
                if len(suggestions) >= max_suggestions:
                    break
        
        return suggestions
