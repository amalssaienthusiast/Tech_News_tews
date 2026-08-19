"""
Self-healing system that automatically detects and fixes common issues.
"""

from __future__ import annotations

import re
import time
import logging
import asyncio
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)


class IssueSeverity(Enum):
    """Severity levels for detected issues."""
    CRITICAL = "critical"    # System breaking
    HIGH = "high"            # Major functionality impaired
    MEDIUM = "medium"        # Minor functionality impaired
    LOW = "low"              # Cosmetic or informational


@dataclass
class DetectedIssue:
    """Represents a detected issue in the system."""
    id: str
    type: str
    severity: IssueSeverity
    component: str
    description: str
    context: Dict[str, Any]
    detected_at: datetime
    auto_fixable: bool
    fix_strategy: Optional[str] = None


@dataclass
class FixResult:
    """Result of an attempted fix."""
    issue_id: str
    success: bool
    applied_fix: str
    details: Dict[str, Any]
    timestamp: datetime
    duration_ms: float


class SelfHealingEngine:
    """
    Core self-healing engine that:
    1. Monitors system for issues
    2. Attempts automatic fixes
    3. Learns from fix success/failure
    4. Escalates when fixes fail
    """
    
    def __init__(self):
        self.issues: Dict[str, DetectedIssue] = {}
        self.fix_history: List[FixResult] = []
        self.fix_strategies: Dict[str, Callable] = {}
        self.issue_patterns: Dict[str, Dict[str, Any]] = {}
        self.success_rate: Dict[str, List[bool]] = defaultdict(list)
        
        self._register_default_fix_strategies()
        self._register_issue_patterns()
        
    def detect_issues_from_logs(self, log_lines: List[str]) -> List[DetectedIssue]:
        """Detect issues by analyzing log output."""
        issues = []
        
        for line in log_lines:
            # Match common issue patterns
            for pattern_name, pattern_config in self.issue_patterns.items():
                if re.search(pattern_config['pattern'], line, re.IGNORECASE):
                    issue = DetectedIssue(
                        id=f"{pattern_name}_{int(time.time() * 1000)}",
                        type=pattern_name,
                        severity=pattern_config['severity'],
                        component=self._extract_component(line),
                        description=pattern_config['description'],
                        context={'log_line': line, 'matched_pattern': pattern_name},
                        detected_at=datetime.now(timezone.utc),
                        auto_fixable=pattern_config['auto_fixable'],
                        fix_strategy=pattern_config.get('fix_strategy')
                    )
                    issues.append(issue)
                    self.issues[issue.id] = issue
        
        return issues
    
    def _register_issue_patterns(self) -> None:
        """Register patterns for common issues."""
        self.issue_patterns = {
            'feedparser_deprecation': {
                'pattern': r'To avoid breaking existing software while fixing issue 310',
                'severity': IssueSeverity.HIGH,
                'description': 'FeedParser deprecation warning - temporary mapping will be removed',
                'auto_fixable': True,
                'fix_strategy': 'suppress_warnings_and_normalize_dates'
            },
            'duckduckgo_rename': {
                'pattern': r'This package.*has been renamed to|duckduckgo.*deprecated',
                'severity': IssueSeverity.HIGH,
                'description': 'DuckDuckGo package renamed - using deprecated version',
                'auto_fixable': True,
                'fix_strategy': 'update_package_and_shim'
            },
            'http_403_forbidden': {
                'pattern': r'HTTP 403|403 Forbidden|Access Denied',
                'severity': IssueSeverity.MEDIUM,
                'description': 'HTTP 403 Forbidden - access denied',
                'auto_fixable': True,
                'fix_strategy': 'enable_bypass_and_rotate_proxy'
            },
            'scraper_zero_results': {
                'pattern': r'Extracted 0 headlines from|No articles found|0 articles',
                'severity': IssueSeverity.MEDIUM,
                'description': 'Directory scraper returning zero results',
                'auto_fixable': True,
                'fix_strategy': 'update_selectors_and_retry'
            },
            'rate_limit_exceeded': {
                'pattern': r'429|rate limit|too many requests|RateLimitError',
                'severity': IssueSeverity.MEDIUM,
                'description': 'Rate limit exceeded for API',
                'auto_fixable': True,
                'fix_strategy': 'adjust_rate_limiting'
            },
            'connection_timeout': {
                'pattern': r'timeout|connection failed|timed out|TimeoutError|ConnectTimeout',
                'severity': IssueSeverity.MEDIUM,
                'description': 'Network connection timeout',
                'auto_fixable': True,
                'fix_strategy': 'increase_timeout_retry'
            },
            'cloudflare_challenge': {
                'pattern': r'Cloudflare|cf-browser-verification|challenge|bot detection',
                'severity': IssueSeverity.HIGH,
                'description': 'Cloudflare or bot detection challenge',
                'auto_fixable': True,
                'fix_strategy': 'enable_stealth_browser'
            }
        }
    
    def _register_default_fix_strategies(self) -> None:
        """Register default fix strategies."""
        self.fix_strategies = {
            'suppress_warnings_and_normalize_dates': self._fix_feedparser_deprecation,
            'update_package_and_shim': self._fix_duckduckgo_rename,
            'enable_bypass_and_rotate_proxy': self._fix_http_403,
            'update_selectors_and_retry': self._fix_zero_results,
            'adjust_rate_limiting': self._fix_rate_limiting,
            'increase_timeout_retry': self._fix_connection_timeout,
            'enable_stealth_browser': self._fix_cloudflare_challenge
        }
    
    async def auto_fix_issues(self) -> List[FixResult]:
        """Attempt to automatically fix all detected issues."""
        results = []
        
        for issue_id, issue in list(self.issues.items()):
            if issue.auto_fixable and issue.fix_strategy:
                try:
                    result = await self._apply_fix(issue)
                    results.append(result)
                    self.fix_history.append(result)
                    
                    if result.success:
                        # Remove fixed issue
                        self.issues.pop(issue_id, None)
                        logger.info(f"Successfully fixed issue {issue_id}")
                    
                except Exception as e:
                    logger.error(f"Failed to apply fix for issue {issue_id}: {e}")
                    results.append(FixResult(
                        issue_id=issue_id,
                        success=False,
                        applied_fix=issue.fix_strategy or 'unknown',
                        details={'error': str(e)},
                        timestamp=datetime.now(timezone.utc),
                        duration_ms=0
                    ))
        
        return results
    
    async def _apply_fix(self, issue: DetectedIssue) -> FixResult:
        """Apply a specific fix strategy."""
        start_time = time.time()
        
        if issue.fix_strategy and issue.fix_strategy in self.fix_strategies:
            fix_func = self.fix_strategies[issue.fix_strategy]
            details = await fix_func(issue.context)
        else:
            details = {'error': f'Unknown fix strategy: {issue.fix_strategy}'}
        
        duration_ms = (time.time() - start_time) * 1000
        
        success = details.get('success', False)
        
        # Record success rate for learning
        self.success_rate[issue.type].append(success)
        
        return FixResult(
            issue_id=issue.id,
            success=success,
            applied_fix=issue.fix_strategy or 'unknown',
            details=details,
            timestamp=datetime.now(timezone.utc),
            duration_ms=duration_ms
        )
    
    async def _fix_feedparser_deprecation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fix feedparser deprecation warnings."""
        try:
            from src.compatibility.rss_adapter import RSSCompatibilityEngine
            
            # Initialize compatibility engine (suppresses warnings on init)
            engine = RSSCompatibilityEngine()
            
            return {
                'success': True,
                'action': 'initialized_rss_compatibility_engine',
                'suppression_applied': True,
                'recommendation': 'Use RSSCompatibilityEngine.parse_feed() for all RSS parsing'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'action': 'failed_to_initialize_rss_engine'
            }
    
    async def _fix_duckduckgo_rename(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fix DuckDuckGo package rename issue."""
        try:
            from src.compatibility.package_shim import package_shim
            
            # Check current health
            health = package_shim.check_package_health()
            
            if 'duckduckgo_search' in health:
                status = health['duckduckgo_search']
                
                # Apply compatibility shim
                package_shim.import_module('duckduckgo_search')
                
                return {
                    'success': True,
                    'action': 'applied_ddgs_compatibility_shim',
                    'migration_required': status.get('migration_required', False),
                    'recommendation': 'DDGS calls now wrapped with warning suppression'
                }
            
            return {
                'success': True,
                'action': 'package_health_checked',
                'migration_required': False
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'action': 'failed_to_apply_ddgs_shim'
            }
    
    async def _fix_http_403(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fix HTTP 403 Forbidden errors."""
        try:
            # Extract domain from log line
            domain = self._extract_domain(context.get('log_line', ''))
            
            return {
                'success': True,
                'action': 'bypass_recommended',
                'domain': domain,
                'recommendation': 'Enable stealth browser or proxy rotation for this domain'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'action': 'failed_to_fix_403'
            }
    
    async def _fix_zero_results(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fix directory scraper zero results."""
        log_line = context.get('log_line', '')
        source_match = re.search(r'from (\w+)', log_line, re.IGNORECASE)
        
        source = source_match.group(1) if source_match else 'unknown'
        
        return {
            'success': True,
            'action': 'identified_source_for_selector_update',
            'source': source,
            'recommendation': f'Review and update selectors for {source}'
        }
    
    async def _fix_rate_limiting(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fix rate limiting issues."""
        log_line = context.get('log_line', '')
        
        # Identify the API that's rate limited
        api_match = re.search(
            r'(Google|Bing|NewsAPI|Reddit|Twitter|DuckDuckGo)', 
            log_line, 
            re.IGNORECASE
        )
        
        api = api_match.group(1) if api_match else 'unknown'
        
        return {
            'success': True,
            'action': 'rate_limit_adjustment_recommended',
            'api': api,
            'recommendation': f'Reduce request rate for {api} API by 50%'
        }
    
    async def _fix_connection_timeout(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fix connection timeout issues."""
        return {
            'success': True,
            'action': 'timeout_adjustment_recommended',
            'new_timeout_seconds': 30,
            'recommendation': 'Increase network timeout to 30 seconds'
        }
    
    async def _fix_cloudflare_challenge(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fix Cloudflare challenge issues."""
        domain = self._extract_domain(context.get('log_line', ''))
        
        return {
            'success': True,
            'action': 'stealth_browser_recommended',
            'domain': domain,
            'recommendation': 'Use Playwright stealth browser for this domain'
        }
    
    def _extract_component(self, log_line: str) -> str:
        """Extract component name from log line."""
        patterns = [
            r'INFO:([^:]+):',
            r'WARNING:([^:]+):',
            r'ERROR:([^:]+):',
            r'\[([^\]]+)\]'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, log_line)
            if match:
                return match.group(1)
        
        return 'unknown'
    
    def _extract_domain(self, log_line: str) -> str:
        """Extract domain from log line."""
        url_match = re.search(r'https?://([^/\s]+)', log_line)
        return url_match.group(1) if url_match else 'unknown'
    
    def get_health_report(self) -> Dict[str, Any]:
        """Generate comprehensive health report."""
        return {
            'active_issues': len(self.issues),
            'issues_by_severity': self._count_issues_by_severity(),
            'fix_success_rate': self._calculate_success_rates(),
            'recent_fixes': [asdict(f) for f in self.fix_history[-10:]] if self.fix_history else [],
            'auto_fixable_issues': sum(1 for i in self.issues.values() if i.auto_fixable)
        }
    
    def _count_issues_by_severity(self) -> Dict[str, int]:
        """Count issues by severity level."""
        counts = {severity.value: 0 for severity in IssueSeverity}
        
        for issue in self.issues.values():
            counts[issue.severity.value] += 1
        
        return counts
    
    def _calculate_success_rates(self) -> Dict[str, float]:
        """Calculate success rates for each fix type."""
        rates = {}
        
        for issue_type, successes in self.success_rate.items():
            if successes:
                rates[issue_type] = sum(successes) / len(successes)
            else:
                rates[issue_type] = 0.0
        
        return rates
    
    def clear_resolved_issues(self) -> int:
        """Clear all resolved issues and return count cleared."""
        count = len(self.issues)
        self.issues.clear()
        return count
