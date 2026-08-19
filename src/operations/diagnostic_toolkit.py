"""
Diagnostic Toolkit for Tech News Scraper.

Provides CLI tools for:
- System health diagnostics
- Component-specific checks
- Automated troubleshooting
- Report generation

Usage:
    # Run all checks
    python -m src.operations.diagnostic_toolkit --check all
    
    # Check specific component
    python -m src.operations.diagnostic_toolkit --check scraping
    python -m src.operations.diagnostic_toolkit --check database
    python -m src.operations.diagnostic_toolkit --check bypass
    
    # Generate diagnostic report
    python -m src.operations.diagnostic_toolkit --generate-report
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CheckResult:
    """Result of a single diagnostic check."""
    name: str
    status: str  # "pass", "warn", "fail"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "duration_ms": round(self.duration_ms, 2),
        }
    
    @property
    def emoji(self) -> str:
        return {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(self.status, "❓")


@dataclass
class DiagnosticReport:
    """Complete diagnostic report."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    checks: List[CheckResult] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary,
            "recommendations": self.recommendations,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    def print_summary(self):
        """Print a human-readable summary to console."""
        print("\n" + "=" * 60)
        print("📊 DIAGNOSTIC REPORT")
        print("=" * 60)
        print(f"Time: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print()
        
        # Print checks
        for check in self.checks:
            print(f"  {check.emoji} {check.name}: {check.message}")
            if check.details:
                for key, value in check.details.items():
                    print(f"      {key}: {value}")
        
        # Print summary
        print()
        print("-" * 60)
        passed = self.summary.get("pass", 0)
        warned = self.summary.get("warn", 0)
        failed = self.summary.get("fail", 0)
        total = passed + warned + failed
        
        print(f"Summary: {passed}/{total} passed, {warned} warnings, {failed} failures")
        
        # Print recommendations
        if self.recommendations:
            print()
            print("📋 Recommendations:")
            for i, rec in enumerate(self.recommendations, 1):
                print(f"  {i}. {rec}")
        
        print("=" * 60 + "\n")


# =============================================================================
# DIAGNOSTIC TOOLKIT
# =============================================================================

class DiagnosticToolkit:
    """
    Comprehensive diagnostic toolkit for the Tech News Scraper.
    
    Provides checks for:
    - Database connectivity and health
    - Redis connectivity
    - External API reachability
    - Scraping components
    - Bypass mechanisms
    - File system permissions
    - Configuration validity
    """
    
    def __init__(self):
        self._checks: Dict[str, callable] = {}
        self._register_checks()
    
    def _register_checks(self):
        """Register all available checks."""
        self._checks = {
            "database": self.check_database,
            "redis": self.check_redis,
            "filesystem": self.check_filesystem,
            "scraping": self.check_scraping,
            "bypass": self.check_bypass,
            "configuration": self.check_configuration,
            "dependencies": self.check_dependencies,
            "api": self.check_external_apis,
        }
    
    async def run_check(self, name: str) -> CheckResult:
        """Run a single named check."""
        if name not in self._checks:
            return CheckResult(
                name=name,
                status="fail",
                message=f"Unknown check: {name}",
            )
        
        import time
        start = time.time()
        
        try:
            check_func = self._checks[name]
            if asyncio.iscoroutinefunction(check_func):
                result = await check_func()
            else:
                result = check_func()
            result.duration_ms = (time.time() - start) * 1000
            return result
        except Exception as e:
            return CheckResult(
                name=name,
                status="fail",
                message=f"Check failed with error: {str(e)}",
                duration_ms=(time.time() - start) * 1000,
            )
    
    async def run_all_checks(self) -> DiagnosticReport:
        """Run all registered checks."""
        report = DiagnosticReport()
        
        for name in self._checks:
            result = await self.run_check(name)
            report.checks.append(result)
        
        # Calculate summary
        report.summary = {
            "pass": len([c for c in report.checks if c.status == "pass"]),
            "warn": len([c for c in report.checks if c.status == "warn"]),
            "fail": len([c for c in report.checks if c.status == "fail"]),
        }
        
        # Generate recommendations
        report.recommendations = self._generate_recommendations(report.checks)
        
        return report
    
    async def run_category(self, category: str) -> DiagnosticReport:
        """Run checks for a specific category."""
        category_lower = category.lower()
        
        if category_lower == "all":
            return await self.run_all_checks()
        
        if category_lower in self._checks:
            result = await self.run_check(category_lower)
            report = DiagnosticReport(checks=[result])
            report.summary = {result.status: 1}
            return report
        
        # Try to find matching checks
        matching = [name for name in self._checks if category_lower in name]
        if not matching:
            return DiagnosticReport(
                checks=[CheckResult(
                    name="error",
                    status="fail",
                    message=f"No checks found for category: {category}",
                )]
            )
        
        report = DiagnosticReport()
        for name in matching:
            result = await self.run_check(name)
            report.checks.append(result)
        
        report.summary = {
            "pass": len([c for c in report.checks if c.status == "pass"]),
            "warn": len([c for c in report.checks if c.status == "warn"]),
            "fail": len([c for c in report.checks if c.status == "fail"]),
        }
        
        return report
    
    # =========================================================================
    # INDIVIDUAL CHECKS
    # =========================================================================
    
    def check_database(self) -> CheckResult:
        """Check database connectivity and health."""
        try:
            import os
            from pathlib import Path
            import sqlite3
            from src.storage.sqlite_engine import DEFAULT_CANONICAL_DB_PATH

            db_path_env = os.getenv("TECHNEWS_CANONICAL_DB_PATH") or os.getenv("CANONICAL_DB_PATH")
            db_path = Path(db_path_env) if db_path_env else DEFAULT_CANONICAL_DB_PATH

            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                table_count = cursor.fetchone()[0]
                try:
                    cursor.execute("SELECT COUNT(*) FROM canonical_articles")
                    article_count = cursor.fetchone()[0]
                except Exception:
                    article_count = 0
                try:
                    cursor.execute("SELECT COUNT(*) FROM source_health")
                    source_count = cursor.fetchone()[0]
                except Exception:
                    source_count = 0

            return CheckResult(
                name="database",
                status="pass",
                message="Database is healthy",
                details={
                    "type": "canonical_sqlite",
                    "articles": article_count,
                    "sources": source_count,
                    "tables": table_count,
                }
            )
        except Exception as e:
            return CheckResult(
                name="database",
                status="fail",
                message=f"Database check failed: {str(e)}",
            )
    
    async def check_redis(self) -> CheckResult:
        """Check Redis connectivity with quick single attempt."""
        try:
            import asyncio
            
            try:
                import redis.asyncio as aioredis
            except ImportError:
                return CheckResult(
                    name="redis",
                    status="warn",
                    message="Redis package not installed (optional)",
                )
            
            # Quick single-attempt check with 2-second timeout
            try:
                redis_client = aioredis.from_url(
                    "redis://localhost:6379/0",
                    encoding="utf-8",
                    decode_responses=True,
                )
                # Use asyncio.wait_for for timeout
                await asyncio.wait_for(redis_client.ping(), timeout=2.0)
                await redis_client.close()
                return CheckResult(
                    name="redis",
                    status="pass",
                    message="Redis is connected",
                )
            except asyncio.TimeoutError:
                return CheckResult(
                    name="redis",
                    status="warn",
                    message="Redis connection timed out (optional)",
                )
            except Exception:
                return CheckResult(
                    name="redis",
                    status="warn",
                    message="Redis not available (optional component)",
                )
        except Exception as e:
            return CheckResult(
                name="redis",
                status="warn",
                message=f"Redis not available: {str(e)[:50]}",
            )
    
    def check_filesystem(self) -> CheckResult:
        """Check filesystem permissions and data directories."""
        try:
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            
            # Check data directory
            if not data_dir.exists():
                data_dir.mkdir(parents=True, exist_ok=True)
            
            # Check write permissions
            test_file = data_dir / ".diagnostic_test"
            test_file.write_text("test")
            test_file.unlink()
            
            # Check disk space
            import shutil
            total, used, free = shutil.disk_usage(data_dir)
            free_gb = free / (1024**3)
            
            if free_gb < 1:
                return CheckResult(
                    name="filesystem",
                    status="warn",
                    message=f"Low disk space: {free_gb:.1f}GB free",
                    details={"free_gb": round(free_gb, 2)},
                )
            
            return CheckResult(
                name="filesystem",
                status="pass",
                message="Filesystem is healthy",
                details={
                    "data_dir": str(data_dir),
                    "free_gb": round(free_gb, 2),
                }
            )
        except Exception as e:
            return CheckResult(
                name="filesystem",
                status="fail",
                message=f"Filesystem check failed: {str(e)}",
            )
    
    def check_scraping(self) -> CheckResult:
        """Check scraping components."""
        try:
            from src.engine.scrape_queue import get_scrape_queue
            queue = get_scrape_queue()
            stats = queue.get_statistics()
            
            return CheckResult(
                name="scraping",
                status="pass",
                message="Scraping components initialized",
                details={
                    "queue_size": stats.get("queue_size", 0),
                    "total_scrapes": stats.get("total_scrapes", 0),
                    "success_rate": f"{stats.get('success_rate', 0)}%",
                }
            )
        except Exception as e:
            return CheckResult(
                name="scraping",
                status="warn",
                message=f"Scraping check: {str(e)[:50]}",
            )
    
    def check_bypass(self) -> CheckResult:
        """Check bypass mechanism availability."""
        try:
            from src.bypass.anti_bot import AntiBotBypass
            
            bypass = AntiBotBypass()
            
            return CheckResult(
                name="bypass",
                status="pass",
                message="Bypass mechanisms available",
                details={
                    "request_delay": f"{bypass._request_delay}s",
                    "blocked_domains": len(bypass._blocked_domains),
                }
            )
        except Exception as e:
            return CheckResult(
                name="bypass",
                status="warn",
                message=f"Bypass check: {str(e)[:50]}",
            )
    
    def check_configuration(self) -> CheckResult:
        """Check configuration files."""
        try:
            project_root = Path(__file__).parent.parent.parent
            config_files = [
                project_root / "config.yaml",
                project_root / "config.py",
                project_root / "src" / "core" / "config.py",
            ]
            
            found = [f for f in config_files if f.exists()]
            
            if found:
                return CheckResult(
                    name="configuration",
                    status="pass",
                    message=f"Configuration found: {len(found)} files",
                    details={"files": [f.name for f in found]},
                )
            else:
                return CheckResult(
                    name="configuration",
                    status="warn",
                    message="No configuration files found (using defaults)",
                )
        except Exception as e:
            return CheckResult(
                name="configuration",
                status="warn",
                message=f"Config check: {str(e)[:50]}",
            )
    
    def check_dependencies(self) -> CheckResult:
        """Check required Python dependencies."""
        required = [
            ("aiohttp", "aiohttp"),
            ("bs4", "beautifulsoup4"),  # bs4 is the import name for beautifulsoup4
            ("feedparser", "feedparser"),
            ("psutil", "psutil"),
        ]
        
        missing = []
        for import_name, package_name in required:
            try:
                __import__(import_name)
            except ImportError:
                missing.append(package_name)
        
        if missing:
            return CheckResult(
                name="dependencies",
                status="fail",
                message=f"Missing packages: {', '.join(missing)}",
                details={"missing": missing},
            )
        
        return CheckResult(
            name="dependencies",
            status="pass",
            message="All required dependencies installed",
        )
    
    async def check_external_apis(self) -> CheckResult:
        """Check external API reachability."""
        import aiohttp
        
        apis = {
            "google": "https://www.google.com",
            "duckduckgo": "https://duckduckgo.com",
        }
        
        # Use proper headers to avoid being blocked
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        
        results = {}
        try:
            from src.utils.http import create_connector
            connector = create_connector()  # Real certifi-backed SSL verification
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                for name, url in apis.items():
                    try:
                        # Use GET instead of HEAD (some sites block HEAD requests)
                        async with session.get(
                            url, 
                            timeout=aiohttp.ClientTimeout(total=5),
                            allow_redirects=True
                        ) as resp:
                            results[name] = resp.status < 400
                    except Exception:
                        results[name] = False
            
            all_ok = all(results.values())
            return CheckResult(
                name="api",
                status="pass" if all_ok else "warn",
                message="External APIs " + ("reachable" if all_ok else "partially reachable"),
                details=results,
            )
        except Exception as e:
            return CheckResult(
                name="api",
                status="warn",
                message=f"API check: {str(e)[:50]}",
            )
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _generate_recommendations(self, checks: List[CheckResult]) -> List[str]:
        """Generate recommendations based on check results."""
        recommendations = []
        
        for check in checks:
            if check.status == "fail":
                if check.name == "database":
                    recommendations.append(
                        "Database connection failed. Ensure SQLite database file "
                        "exists and has correct permissions."
                    )
                elif check.name == "dependencies":
                    recommendations.append(
                        "Install missing dependencies: pip install <package>"
                    )
                elif check.name == "filesystem":
                    recommendations.append(
                        "Check disk space and directory permissions for data folder."
                    )
            
            elif check.status == "warn":
                if check.name == "redis":
                    recommendations.append(
                        "Redis is optional but recommended for real-time features. "
                        "Install with: docker run -p 6379:6379 redis"
                    )
                elif "disk" in check.message.lower():
                    recommendations.append(
                        "Consider cleaning up old data or expanding disk space."
                    )
        
        return recommendations


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    """CLI entry point for diagnostic toolkit."""
    parser = argparse.ArgumentParser(
        description="Tech News Scraper Diagnostic Toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.operations.diagnostic_toolkit --check all
  python -m src.operations.diagnostic_toolkit --check database
  python -m src.operations.diagnostic_toolkit --check scraping
  python -m src.operations.diagnostic_toolkit --generate-report
        """
    )
    
    parser.add_argument(
        "--check",
        choices=["all", "database", "redis", "filesystem", "scraping", 
                 "bypass", "configuration", "dependencies", "api"],
        default="all",
        help="Component to check (default: all)"
    )
    
    parser.add_argument(
        "--generate-report",
        action="store_true",
        help="Generate JSON diagnostic report"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for report (default: stdout)"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    
    args = parser.parse_args()
    
    # Run diagnostics
    toolkit = DiagnosticToolkit()
    
    async def run():
        if args.generate_report or args.check == "all":
            report = await toolkit.run_all_checks()
        else:
            report = await toolkit.run_category(args.check)
        
        if args.json or args.generate_report:
            output = report.to_json()
            if args.output:
                Path(args.output).write_text(output)
                print(f"Report saved to: {args.output}")
            else:
                print(output)
        else:
            report.print_summary()
    
    asyncio.run(run())


if __name__ == "__main__":
    main()
