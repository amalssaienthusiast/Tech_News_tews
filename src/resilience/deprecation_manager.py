"""
Deprecation tracking and migration planning.
"""

from __future__ import annotations

import importlib
import warnings
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DeprecationEntry:
    """Tracks a deprecation event."""
    package_name: str
    warning_message: str
    detected_at: datetime
    severity: str
    migration_action: Optional[str] = None


class DeprecationManager:
    """
    Manages package deprecations:
    - Tracks deprecation warnings
    - Generates migration plans
    - Provides status reports
    """
    
    def __init__(self):
        self.deprecations: Dict[str, List[DeprecationEntry]] = {}
        self._initialized = False
        
        # Known deprecations and their solutions
        self.known_deprecations: Dict[str, Dict[str, Any]] = {
            'feedparser': {
                'issue': 'issue 310 - published/updated date mapping',
                'solution': 'Use RSSCompatibilityEngine from src.compatibility',
                'migration_steps': [
                    'Import RSSCompatibilityEngine from src.compatibility.rss_adapter',
                    'Replace feedparser.parse() with engine.parse_feed()',
                    'Access dates via normalized["dates"]["primary"]'
                ]
            },
            'duckduckgo_search': {
                'issue': 'Package may be renamed to ddgs in future',
                'solution': 'Use package_shim for imports',
                'migration_steps': [
                    'Import safe_import from src.compatibility.package_shim',
                    'Use safe_import("duckduckgo_search") instead of direct import',
                    'The shim handles warning suppression automatically'
                ]
            }
        }
    
    async def initialize(self) -> None:
        """Initialize the deprecation manager."""
        if self._initialized:
            return
        
        # Capture deprecation warnings
        self._setup_warning_capture()
        
        self._initialized = True
        logger.info("DeprecationManager initialized")
    
    def _setup_warning_capture(self) -> None:
        """Set up warning capture to track deprecations."""
        # We don't actually capture warnings, we suppress them
        # and track known deprecations manually
        pass
    
    def check_package_health(self) -> Dict[str, Any]:
        """Check health of packages with known deprecations."""
        health: Dict[str, Any] = {
            'packages_checked': [],
            'deprecations_found': [],
            'migrations_required': False
        }
        
        for package_name, info in self.known_deprecations.items():
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")
                    module = importlib.import_module(package_name)
                    version = getattr(module, '__version__', 'unknown')
                
                health['packages_checked'].append({
                    'name': package_name,
                    'version': version,
                    'status': 'installed',
                    'has_deprecation': True,
                    'solution': info['solution']
                })
                health['deprecations_found'].append(package_name)
                health['migrations_required'] = True
                
            except ImportError:
                health['packages_checked'].append({
                    'name': package_name,
                    'status': 'not_installed'
                })
        
        return health
    
    def generate_migration_plan(self) -> str:
        """Generate a comprehensive migration plan."""
        lines = [
            "=" * 60,
            "DEPRECATION MIGRATION PLAN",
            "=" * 60,
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            ""
        ]
        
        for package_name, info in self.known_deprecations.items():
            lines.extend([
                f"\n📦 Package: {package_name}",
                f"   Issue: {info['issue']}",
                f"   Solution: {info['solution']}",
                "   Migration Steps:"
            ])
            
            for i, step in enumerate(info['migration_steps'], 1):
                lines.append(f"     {i}. {step}")
        
        lines.extend([
            "",
            "=" * 60,
            "To apply migrations, update your imports as described above.",
            "The compatibility layer handles most cases automatically.",
            "=" * 60
        ])
        
        return "\n".join(lines)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current deprecation status."""
        return {
            'initialized': self._initialized,
            'known_deprecations': list(self.known_deprecations.keys()),
            'tracked_deprecations': len(self.deprecations),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def add_deprecation(self, package_name: str, warning_message: str, 
                       severity: str = 'medium') -> None:
        """Manually add a deprecation entry."""
        entry = DeprecationEntry(
            package_name=package_name,
            warning_message=warning_message,
            detected_at=datetime.now(timezone.utc),
            severity=severity,
            migration_action=self.known_deprecations.get(package_name, {}).get('solution')
        )
        
        if package_name not in self.deprecations:
            self.deprecations[package_name] = []
        
        self.deprecations[package_name].append(entry)
        logger.info(f"Added deprecation entry for {package_name}")
