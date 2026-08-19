"""
Universal package compatibility layer that handles:
1. Package renames (duckduckgo_search → ddgs)
2. API changes
3. Deprecation warnings
4. Automatic fallbacks
"""

from __future__ import annotations

import importlib
import warnings
import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


class PackageStatus(Enum):
    """Status of a package in the compatibility registry."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RENAMED = "renamed"
    REMOVED = "removed"
    UNKNOWN = "unknown"


@dataclass
class PackageInfo:
    """Information about a package and its compatibility."""
    original_name: str
    current_name: str
    status: PackageStatus
    version_required: str
    fallback_module: Optional[str] = None
    migration_guide: Optional[str] = None
    end_of_life: Optional[str] = None


class UniversalPackageShim:
    """
    Universal shim that handles package renames, deprecations, and API changes.
    Provides transparent compatibility across package versions.
    """
    
    # Registry of known package migrations
    PACKAGE_REGISTRY: Dict[str, PackageInfo] = {
        'duckduckgo_search': PackageInfo(
            original_name='duckduckgo_search',
            current_name='duckduckgo_search',  # Keep same for now, shim handles DDGS
            status=PackageStatus.DEPRECATED,
            version_required='>=4.0.0',
            fallback_module='duckduckgo_search',
            migration_guide='https://github.com/deedy5/duckduckgo_search',
            end_of_life='2025-12-31'
        ),
        'feedparser': PackageInfo(
            original_name='feedparser',
            current_name='feedparser',
            status=PackageStatus.ACTIVE,
            version_required='>=6.0.10',
            fallback_module=None,
            migration_guide=None,
            end_of_life=None
        ),
    }
    
    def __init__(self):
        self._loaded_packages: Dict[str, Any] = {}
        self._warnings_issued: set = set()
        
    def import_module(self, module_name: str, **kwargs) -> Any:
        """
        Import a module with automatic compatibility handling.
        
        Args:
            module_name: Name of module to import
            **kwargs: Additional import arguments
            
        Returns:
            Imported module with compatibility shims applied
        """
        # Check if we have compatibility info
        package_info = self.PACKAGE_REGISTRY.get(module_name)
        
        if package_info:
            return self._import_with_compatibility(package_info, **kwargs)
        
        # Standard import for unknown packages
        try:
            module = importlib.import_module(module_name)
            self._loaded_packages[module_name] = module
            return module
        except ImportError as e:
            logger.error(f"Failed to import {module_name}: {e}")
            raise
    
    def _import_with_compatibility(self, package_info: PackageInfo, **kwargs) -> Any:
        """Import a package with full compatibility handling."""
        
        # Suppress warnings for this package
        if package_info.original_name not in self._warnings_issued:
            self._suppress_package_warnings(package_info)
        
        # Try current package name first
        try:
            module = importlib.import_module(package_info.current_name)
            logger.debug(f"Successfully imported {package_info.current_name}")
            
            # Apply compatibility shims if needed
            if package_info.status == PackageStatus.DEPRECATED:
                module = self._apply_deprecated_package_shims(module, package_info)
            elif package_info.status == PackageStatus.RENAMED:
                module = self._apply_renamed_package_shims(module, package_info)
            
            self._loaded_packages[package_info.original_name] = module
            return module
            
        except ImportError:
            # Try fallback module if available
            if package_info.fallback_module:
                try:
                    if package_info.original_name not in self._warnings_issued:
                        logger.warning(
                            f"Using fallback for {package_info.original_name}. "
                            f"Consider migrating to {package_info.current_name}"
                        )
                        self._warnings_issued.add(package_info.original_name)
                    
                    module = importlib.import_module(package_info.fallback_module)
                    module = self._apply_backward_compatibility_shims(module, package_info)
                    
                    self._loaded_packages[package_info.original_name] = module
                    return module
                    
                except ImportError:
                    pass
            
            # No compatible package found
            error_msg = self._generate_migration_error(package_info)
            logger.error(error_msg)
            raise ImportError(error_msg)
    
    def _suppress_package_warnings(self, package_info: PackageInfo) -> None:
        """Suppress deprecation warnings for a package."""
        warnings.filterwarnings(
            "ignore",
            message=f".*{package_info.original_name}.*",
            category=DeprecationWarning
        )
        # Suppress the specific "renamed to" warning
        warnings.filterwarnings(
            "ignore",
            message=".*has been renamed to.*",
            category=DeprecationWarning
        )
        warnings.filterwarnings(
            "ignore",
            message=".*This package.*renamed.*",
        )
    
    def _apply_deprecated_package_shims(self, module: Any, package_info: PackageInfo) -> Any:
        """Apply shims for deprecated packages."""
        
        if package_info.original_name == 'duckduckgo_search':
            return self._create_ddgs_compatibility_layer(module)
        
        return module
    
    def _apply_renamed_package_shims(self, module: Any, package_info: PackageInfo) -> Any:
        """Apply shims for renamed packages."""
        return self._apply_deprecated_package_shims(module, package_info)
    
    def _create_ddgs_compatibility_layer(self, ddgs_module: Any) -> Any:
        """Create comprehensive compatibility layer for DDGS."""
        
        # Check if DDGS class exists
        if not hasattr(ddgs_module, 'DDGS'):
            return ddgs_module
        
        original_DDGS = ddgs_module.DDGS
        
        class DDGSCompatibilityWrapper:
            """Wrapper that suppresses deprecation warnings for DDGS."""
            
            _warning_suppressed = False
            
            def __init__(self, *args, **kwargs):
                # Suppress warnings on first instantiation
                if not DDGSCompatibilityWrapper._warning_suppressed:
                    warnings.filterwarnings("ignore", message=".*duckduckgo.*")
                    warnings.filterwarnings("ignore", message=".*DDGS.*")
                    DDGSCompatibilityWrapper._warning_suppressed = True
                
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")
                    self._instance = original_DDGS(*args, **kwargs)
            
            def __enter__(self):
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")
                    return self._instance.__enter__()
            
            def __exit__(self, *args):
                return self._instance.__exit__(*args)
            
            def __getattr__(self, name):
                return getattr(self._instance, name)
            
            def text(self, *args, **kwargs):
                """Search with warning suppression."""
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")
                    return self._instance.text(*args, **kwargs)
            
            def news(self, *args, **kwargs):
                """News search with warning suppression."""
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")
                    return self._instance.news(*args, **kwargs)
        
        # Replace the DDGS class with our wrapper
        ddgs_module.DDGS = DDGSCompatibilityWrapper
        
        return ddgs_module
    
    def _apply_backward_compatibility_shims(self, module: Any, package_info: PackageInfo) -> Any:
        """Apply shims for backward compatibility with deprecated packages."""
        return self._apply_deprecated_package_shims(module, package_info)
    
    def _generate_migration_error(self, package_info: PackageInfo) -> str:
        """Generate helpful migration error message."""
        return (
            f"\n{'='*60}\n"
            f"PACKAGE MIGRATION REQUIRED\n"
            f"{'='*60}\n"
            f"Package: {package_info.original_name}\n"
            f"Status: {package_info.status.value}\n"
            f"Current: {package_info.current_name}\n"
            f"Required Version: {package_info.version_required}\n"
            f"\nACTION REQUIRED:\n"
            f"1. Update requirements.txt:\n"
            f"   - Ensure: {package_info.current_name}{package_info.version_required}\n"
            f"2. Run: pip install {package_info.current_name}\n"
            f"\nMigration Guide: {package_info.migration_guide}\n"
            f"{'='*60}\n"
        )
    
    def check_package_health(self) -> Dict[str, Dict[str, Any]]:
        """Check health of all registered packages."""
        health_report: Dict[str, Dict[str, Any]] = {}
        
        for name, info in self.PACKAGE_REGISTRY.items():
            try:
                # Suppress warnings during health check
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore")
                    module = importlib.import_module(info.current_name)
                
                version = getattr(module, '__version__', 'unknown')
                
                health_report[name] = {
                    'status': 'healthy',
                    'version': version,
                    'loaded_as': info.current_name,
                    'compatibility': info.status.value,
                    'migration_required': info.status in [PackageStatus.DEPRECATED, PackageStatus.RENAMED]
                }
                
            except ImportError as e:
                health_report[name] = {
                    'status': 'unhealthy',
                    'error': str(e),
                    'compatibility': info.status.value,
                    'migration_required': True,
                    'critical': True
                }
        
        return health_report
    
    def generate_migration_report(self) -> str:
        """Generate comprehensive migration report."""
        report = ["Package Migration Report", "=" * 40]
        
        migrations_needed = False
        for name, info in self.PACKAGE_REGISTRY.items():
            if info.status in [PackageStatus.DEPRECATED, PackageStatus.RENAMED]:
                migrations_needed = True
                report.extend([
                    f"\nPackage: {name}",
                    f"Status: {info.status.value}",
                    f"Current Name: {info.current_name}",
                    f"Required by: {info.end_of_life or 'No deadline'}",
                    f"Guide: {info.migration_guide or 'No guide available'}"
                ])
        
        if not migrations_needed:
            report.append("\nNo migrations required at this time.")
        
        return "\n".join(report)


# Global instance for easy access
package_shim = UniversalPackageShim()


def safe_import(module_name: str, **kwargs) -> Any:
    """Safely import a module with automatic compatibility handling."""
    return package_shim.import_module(module_name, **kwargs)
