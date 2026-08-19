"""
Resilience System - Main entry point for permanent solutions.

This package provides:
- Self-healing mechanisms for common issues
- Deprecation tracking and migration planning
- Source health monitoring
- Warning aggregation and suppression
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict
from datetime import datetime, timezone

from .auto_fixer import SelfHealingEngine, DetectedIssue, FixResult, IssueSeverity
from .deprecation_manager import DeprecationManager
from .source_health import SourceHealthMonitor, SourceStatus, HealthCheckResult
from .warning_orchestrator import WarningOrchestrator

logger = logging.getLogger(__name__)

__all__ = [
    # Main system
    "ResilienceSystem",
    "resilience",
    # Auto-fixer
    "SelfHealingEngine",
    "DetectedIssue",
    "FixResult",
    "IssueSeverity",
    # Deprecation
    "DeprecationManager",
    # Source health
    "SourceHealthMonitor",
    "SourceStatus",
    "HealthCheckResult",
    # Warnings
    "WarningOrchestrator",
]


class ResilienceSystem:
    """
    Main resilience system that orchestrates all permanent solutions.
    
    Usage:
        from src.resilience import resilience
        
        # Initialize (call once at startup)
        await resilience.initialize()
        
        # Get system health
        health = resilience.get_system_health()
        
        # Auto-fix detected issues
        result = await resilience.auto_fix_all()
    """
    
    def __init__(self):
        self.self_healing = SelfHealingEngine()
        self.deprecation_mgr = DeprecationManager()
        self.source_health = SourceHealthMonitor()
        self.warning_mgr = WarningOrchestrator()
        
        self._initialized = False
        self._background_tasks: list = []
    
    async def initialize(self) -> None:
        """Initialize the resilience system."""
        if self._initialized:
            return
        
        # Initialize all components
        await self.deprecation_mgr.initialize()
        await self.source_health.initialize()
        await self.warning_mgr.initialize()
        
        # Apply compatibility layers on startup
        self._apply_compatibility_layers()
        
        self._initialized = True
        logger.info("✅ Resilience System Initialized")
    
    def _apply_compatibility_layers(self) -> None:
        """Apply all compatibility layers on startup."""
        try:
            # Initialize RSS compatibility
            from src.compatibility.rss_adapter import RSSCompatibilityEngine
            RSSCompatibilityEngine()  # Suppresses warnings on init
            
            # Initialize package shim
            from src.compatibility.package_shim import package_shim
            package_shim.check_package_health()  # Applies shims
            
            logger.info("Compatibility layers applied")
        except Exception as e:
            logger.warning(f"Could not apply all compatibility layers: {e}")
    
    def start_background_monitoring(self) -> None:
        """Start background monitoring tasks (non-blocking)."""
        try:
            asyncio.get_running_loop()  # raises RuntimeError if no loop is running
            self._background_tasks.append(
                asyncio.create_task(self._background_health_check())
            )
        except RuntimeError:
            logger.debug("No running event loop, skipping background tasks")
    
    async def _background_health_check(self) -> None:
        """Background task for continuous health checking."""
        while True:
            try:
                # Check package health
                from src.compatibility.package_shim import package_shim
                package_health = package_shim.check_package_health()
                
                # Check source health
                source_health = await self.source_health.check_all_sources()
                
                # Log if issues found
                migrations_needed = any(
                    p.get('migration_required') 
                    for p in package_health.values()
                )
                unhealthy_sources = source_health.get('unhealthy_sources', [])
                
                if migrations_needed or unhealthy_sources:
                    logger.warning(
                        f"Health check: {len(unhealthy_sources)} unhealthy sources, "
                        f"migrations_needed={migrations_needed}"
                    )
                
                await asyncio.sleep(300)  # 5 minutes
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(60)
    
    async def auto_fix_all(self) -> Dict[str, Any]:
        """Attempt to automatically fix all detected issues."""
        results: Dict[str, Any] = {
            'success': True,
            'fixes_applied': [],
            'issues_remaining': []
        }
        
        # Run self-healing
        fix_results = await self.self_healing.auto_fix_issues()
        
        for result in fix_results:
            if result.success:
                results['fixes_applied'].append({
                    'issue': result.issue_id,
                    'fix': result.applied_fix,
                    'duration_ms': result.duration_ms
                })
            else:
                results['issues_remaining'].append(result.issue_id)
                results['success'] = False
        
        return results
    
    def detect_issues(self, log_lines: list) -> list:
        """Detect issues from log lines."""
        return self.self_healing.detect_issues_from_logs(log_lines)
    
    def generate_migration_plan(self) -> str:
        """Generate comprehensive migration plan."""
        return self.deprecation_mgr.generate_migration_plan()
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get comprehensive system health status."""
        return {
            'self_healing': self.self_healing.get_health_report(),
            'deprecations': self.deprecation_mgr.get_status(),
            'sources': self.source_health.get_summary_report(),
            'warnings': self.warning_mgr.get_summary(),
            'initialized': self._initialized,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def record_source_check(self, source: str, success: bool, 
                           response_time_ms: float, articles: int = 0,
                           error: str = None) -> None:
        """Record a source health check."""
        result = HealthCheckResult(
            source_name=source,
            success=success,
            response_time_ms=response_time_ms,
            articles_found=articles,
            error=error
        )
        self.source_health.record_check(result)
    
    async def shutdown(self) -> None:
        """Gracefully shutdown the resilience system."""
        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._background_tasks.clear()
        logger.info("Resilience System shut down")


# Global instance for easy access
resilience = ResilienceSystem()
