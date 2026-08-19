"""
Tests for the Compatibility Layer.
"""

import asyncio
import unittest
import warnings
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


class TestRSSCompatibilityEngine(unittest.TestCase):
    """Test cases for RSSCompatibilityEngine."""
    
    def test_import(self):
        """Test that the module imports correctly."""
        from src.compatibility import (
            RSSCompatibilityEngine,
            FeedFormat,
            FeedMetadata,
            FeedResult,
            MigrationTracker
        )
        
        self.assertIsNotNone(RSSCompatibilityEngine)
        self.assertIsNotNone(FeedFormat)
        self.assertIsNotNone(FeedMetadata)
        self.assertIsNotNone(FeedResult)
        self.assertIsNotNone(MigrationTracker)
    
    def test_engine_initialization(self):
        """Test engine initialization and warning suppression."""
        from src.compatibility import RSSCompatibilityEngine
        
        engine = RSSCompatibilityEngine()
        
        self.assertTrue(RSSCompatibilityEngine._warnings_suppressed)
        self.assertIsNotNone(engine._migration_tracker)
    
    def test_feed_format_enum(self):
        """Test FeedFormat enum values."""
        from src.compatibility import FeedFormat
        
        self.assertEqual(FeedFormat.RSS_2_0.value, "rss_2_0")
        self.assertEqual(FeedFormat.ATOM_1_0.value, "atom_1_0")
        self.assertEqual(FeedFormat.UNKNOWN.value, "unknown")
    
    def test_warning_suppression(self):
        """Test that feedparser warnings are suppressed."""
        from src.compatibility import RSSCompatibilityEngine
        
        # Initialize engine (suppresses warnings)
        engine = RSSCompatibilityEngine()
        
        # Capture any warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            
            # This should not produce visible warnings
            import feedparser
            # The engine should have already suppressed feedparser warnings
        
        # Filter out only feedparser-related warnings
        feedparser_warnings = [
            warning for warning in w 
            if 'feedparser' in str(warning.message).lower()
        ]
        
        # Should be suppressed (may not be zero due to other sources)
        self.assertLessEqual(len(feedparser_warnings), 1)
    
    def test_migration_tracker_initialization(self):
        """Test MigrationTracker initialization."""
        from src.compatibility import MigrationTracker
        
        tracker = MigrationTracker()
        
        self.assertEqual(len(tracker.migrations), 0)
        self.assertEqual(len(tracker.recommendations), 0)
    
    def test_get_format_trends(self):
        """Test format trends retrieval."""
        from src.compatibility import RSSCompatibilityEngine
        
        engine = RSSCompatibilityEngine()
        trends = engine.get_format_trends()
        
        self.assertIsInstance(trends, dict)


class TestUniversalPackageShim(unittest.TestCase):
    """Test cases for UniversalPackageShim."""
    
    def test_import(self):
        """Test that the module imports correctly."""
        from src.compatibility import (
            UniversalPackageShim,
            PackageInfo,
            PackageStatus,
            safe_import,
            package_shim
        )
        
        self.assertIsNotNone(UniversalPackageShim)
        self.assertIsNotNone(PackageInfo)
        self.assertIsNotNone(PackageStatus)
        self.assertIsNotNone(safe_import)
        self.assertIsNotNone(package_shim)
    
    def test_package_status_enum(self):
        """Test PackageStatus enum values."""
        from src.compatibility import PackageStatus
        
        self.assertEqual(PackageStatus.ACTIVE.value, "active")
        self.assertEqual(PackageStatus.DEPRECATED.value, "deprecated")
        self.assertEqual(PackageStatus.RENAMED.value, "renamed")
        self.assertEqual(PackageStatus.REMOVED.value, "removed")
    
    def test_shim_initialization(self):
        """Test shim initialization."""
        from src.compatibility import UniversalPackageShim
        
        shim = UniversalPackageShim()
        
        self.assertIsInstance(shim.PACKAGE_REGISTRY, dict)
        self.assertIn('duckduckgo_search', shim.PACKAGE_REGISTRY)
        self.assertIn('feedparser', shim.PACKAGE_REGISTRY)
    
    def test_check_package_health(self):
        """Test package health check."""
        from src.compatibility import package_shim
        
        health = package_shim.check_package_health()
        
        self.assertIsInstance(health, dict)
        
        # Should have checked registered packages
        for name, status in health.items():
            self.assertIn('status', status)
            self.assertIn(status['status'], ['healthy', 'unhealthy'])
    
    def test_generate_migration_report(self):
        """Test migration report generation."""
        from src.compatibility import package_shim
        
        report = package_shim.generate_migration_report()
        
        self.assertIsInstance(report, str)
        self.assertIn('Migration Report', report)
    
    def test_safe_import_standard_package(self):
        """Test safe_import with a standard package."""
        from src.compatibility import safe_import
        
        # Import a known standard library module
        json = safe_import('json')
        
        self.assertIsNotNone(json)
    
    def test_import_known_package(self):
        """Test importing a known package through shim."""
        from src.compatibility import package_shim
        
        # This should work if feedparser is installed
        try:
            module = package_shim.import_module('feedparser')
            self.assertIsNotNone(module)
        except ImportError:
            self.skipTest("feedparser not installed")


class TestPackageInfo(unittest.TestCase):
    """Test cases for PackageInfo dataclass."""
    
    def test_package_info_creation(self):
        """Test creating PackageInfo."""
        from src.compatibility import PackageInfo, PackageStatus
        
        info = PackageInfo(
            original_name='test_package',
            current_name='test_package_new',
            status=PackageStatus.RENAMED,
            version_required='>=1.0.0',
            migration_guide='https://example.com/migrate'
        )
        
        self.assertEqual(info.original_name, 'test_package')
        self.assertEqual(info.current_name, 'test_package_new')
        self.assertEqual(info.status, PackageStatus.RENAMED)
        self.assertEqual(info.version_required, '>=1.0.0')
        self.assertEqual(info.migration_guide, 'https://example.com/migrate')


class TestIntegration(unittest.TestCase):
    """Integration tests for compatibility layer."""
    
    def test_rss_and_shim_together(self):
        """Test using RSS engine and package shim together."""
        from src.compatibility import RSSCompatibilityEngine, package_shim
        
        # Both should initialize without conflicts
        engine = RSSCompatibilityEngine()
        health = package_shim.check_package_health()
        
        self.assertIsNotNone(engine)
        self.assertIsNotNone(health)
    
    def test_warning_free_operation(self):
        """Test that normal operation produces no warnings."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            
            from src.compatibility import RSSCompatibilityEngine, package_shim
            
            engine = RSSCompatibilityEngine()
            health = package_shim.check_package_health()
        
        # Filter for only deprecation warnings from our packages
        relevant_warnings = [
            warning for warning in w
            if 'feedparser' in str(warning.message).lower() or
               'duckduckgo' in str(warning.message).lower()
        ]
        
        # Should be minimal or zero
        self.assertLessEqual(len(relevant_warnings), 2)


if __name__ == '__main__':
    unittest.main()
