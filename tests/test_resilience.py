"""
Tests for the Resilience System.
"""

import asyncio
import unittest
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


class TestSelfHealingEngine(unittest.TestCase):
    """Test cases for SelfHealingEngine."""
    
    def test_import(self):
        """Test that the module imports correctly."""
        from src.resilience import SelfHealingEngine, DetectedIssue, IssueSeverity
        
        self.assertIsNotNone(SelfHealingEngine)
        self.assertIsNotNone(DetectedIssue)
        self.assertIsNotNone(IssueSeverity)
    
    def test_engine_initialization(self):
        """Test engine initialization."""
        from src.resilience import SelfHealingEngine
        
        engine = SelfHealingEngine()
        
        self.assertIsInstance(engine.issues, dict)
        self.assertIsInstance(engine.fix_strategies, dict)
        self.assertIsInstance(engine.issue_patterns, dict)
    
    def test_issue_detection_feedparser(self):
        """Test detection of feedparser deprecation warning."""
        from src.resilience import SelfHealingEngine
        
        engine = SelfHealingEngine()
        
        log_lines = [
            "WARNING:feedparser:To avoid breaking existing software while fixing issue 310"
        ]
        
        issues = engine.detect_issues_from_logs(log_lines)
        
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].type, 'feedparser_deprecation')
        self.assertTrue(issues[0].auto_fixable)
    
    def test_issue_detection_rate_limit(self):
        """Test detection of rate limit errors."""
        from src.resilience import SelfHealingEngine
        
        engine = SelfHealingEngine()
        
        log_lines = [
            "ERROR:api:HTTP 429 Too Many Requests for Google API"
        ]
        
        issues = engine.detect_issues_from_logs(log_lines)
        
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].type, 'rate_limit_exceeded')
    
    def test_health_report(self):
        """Test health report generation."""
        from src.resilience import SelfHealingEngine
        
        engine = SelfHealingEngine()
        
        report = engine.get_health_report()
        
        self.assertIn('active_issues', report)
        self.assertIn('issues_by_severity', report)
        self.assertIn('fix_success_rate', report)
        self.assertIn('auto_fixable_issues', report)


class TestResilienceSystem(unittest.TestCase):
    """Test cases for ResilienceSystem."""
    
    def test_import(self):
        """Test that the module imports correctly."""
        from src.resilience import ResilienceSystem, resilience
        
        self.assertIsNotNone(ResilienceSystem)
        self.assertIsNotNone(resilience)
    
    def test_initialization(self):
        """Test system initialization."""
        from src.resilience import ResilienceSystem
        
        system = ResilienceSystem()
        
        self.assertFalse(system._initialized)
        self.assertIsNotNone(system.self_healing)
        self.assertIsNotNone(system.deprecation_mgr)
        self.assertIsNotNone(system.source_health)
        self.assertIsNotNone(system.warning_mgr)
    
    def test_async_initialization(self):
        """Test async initialization."""
        from src.resilience import ResilienceSystem
        
        system = ResilienceSystem()
        
        async def test():
            await system.initialize()
            return system._initialized
        
        result = asyncio.run(test())
        self.assertTrue(result)
    
    def test_get_system_health(self):
        """Test get_system_health method."""
        from src.resilience import ResilienceSystem
        
        system = ResilienceSystem()
        
        async def test():
            await system.initialize()
            return system.get_system_health()
        
        health = asyncio.run(test())
        
        self.assertIn('self_healing', health)
        self.assertIn('deprecations', health)
        self.assertIn('sources', health)
        self.assertIn('warnings', health)
        self.assertIn('initialized', health)
        self.assertTrue(health['initialized'])
    
    def test_generate_migration_plan(self):
        """Test migration plan generation."""
        from src.resilience import ResilienceSystem
        
        system = ResilienceSystem()
        
        plan = system.generate_migration_plan()
        
        self.assertIsInstance(plan, str)
        self.assertIn('MIGRATION PLAN', plan)


class TestDeprecationManager(unittest.TestCase):
    """Test cases for DeprecationManager."""
    
    def test_import(self):
        """Test that the module imports correctly."""
        from src.resilience import DeprecationManager
        
        self.assertIsNotNone(DeprecationManager)
    
    def test_check_package_health(self):
        """Test package health check."""
        from src.resilience.deprecation_manager import DeprecationManager
        
        manager = DeprecationManager()
        health = manager.check_package_health()
        
        self.assertIn('packages_checked', health)
        self.assertIn('deprecations_found', health)
        self.assertIn('migrations_required', health)
    
    def test_get_status(self):
        """Test status retrieval."""
        from src.resilience.deprecation_manager import DeprecationManager
        
        manager = DeprecationManager()
        status = manager.get_status()
        
        self.assertIn('initialized', status)
        self.assertIn('known_deprecations', status)


class TestSourceHealthMonitor(unittest.TestCase):
    """Test cases for SourceHealthMonitor."""
    
    def test_import(self):
        """Test that the module imports correctly."""
        from src.resilience import SourceHealthMonitor, SourceStatus
        
        self.assertIsNotNone(SourceHealthMonitor)
        self.assertIsNotNone(SourceStatus)
    
    def test_record_check(self):
        """Test recording health checks."""
        from src.resilience import SourceHealthMonitor, HealthCheckResult
        
        monitor = SourceHealthMonitor()
        
        result = HealthCheckResult(
            source_name='test_source',
            success=True,
            response_time_ms=100.0,
            articles_found=10
        )
        
        monitor.record_check(result)
        
        self.assertIn('test_source', monitor.check_history)
        self.assertEqual(len(monitor.check_history['test_source']), 1)
    
    def test_summary_report(self):
        """Test summary report generation."""
        from src.resilience import SourceHealthMonitor
        
        monitor = SourceHealthMonitor()
        report = monitor.get_summary_report()
        
        self.assertIn('total', report)
        self.assertIn('healthy', report)
        self.assertIn('degraded', report)
        self.assertIn('unhealthy', report)


class TestWarningOrchestrator(unittest.TestCase):
    """Test cases for WarningOrchestrator."""
    
    def test_import(self):
        """Test that the module imports correctly."""
        from src.resilience import WarningOrchestrator
        
        self.assertIsNotNone(WarningOrchestrator)
    
    def test_record_warning(self):
        """Test recording warnings."""
        from src.resilience.warning_orchestrator import WarningOrchestrator
        
        orchestrator = WarningOrchestrator()
        
        orchestrator.record_warning(
            "Test warning message",
            category="TestCategory",
            source="TestSource"
        )
        
        self.assertEqual(len(orchestrator.warnings), 1)
    
    def test_get_summary(self):
        """Test summary retrieval."""
        from src.resilience.warning_orchestrator import WarningOrchestrator
        
        orchestrator = WarningOrchestrator()
        summary = orchestrator.get_summary()
        
        self.assertIn('total_warnings', summary)
        self.assertIn('unique_warnings', summary)
        self.assertIn('suppressed_patterns', summary)


if __name__ == '__main__':
    unittest.main()
