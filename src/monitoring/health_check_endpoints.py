"""
Health Check Endpoints for Tech News Scraper.

Provides comprehensive health monitoring for:
- Liveness checks (is the application running?)
- Readiness checks (is the application ready to accept traffic?)
- Detailed component health (database, Redis, APIs, etc.)

Endpoints:
- GET /health - Basic liveness
- GET /health/readiness - Ready for traffic
- GET /health/detailed - Component breakdown
- GET /metrics - Prometheus metrics

Usage:
    from src.monitoring import HealthChecker
    
    checker = HealthChecker()
    
    # Get detailed health
    health = await checker.check_all()
    
    # Check specific component
    db_health = await checker.check_database()
"""

import asyncio
import logging
import os
import psutil
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ComponentHealth:
    """Health status of a single component."""
    name: str
    status: str  # "healthy", "degraded", "unhealthy"
    latency_ms: float = 0
    details: Dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
            "error": self.error,
        }


@dataclass
class SystemHealth:
    """Overall system health."""
    status: str  # "healthy", "degraded", "unhealthy"
    components: List[ComponentHealth] = field(default_factory=list)
    uptime_seconds: float = 0
    version: str = "1.0.0"
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "version": self.version,
            "checked_at": self.checked_at.isoformat(),
            "components": [c.to_dict() for c in self.components],
        }


# =============================================================================
# HEALTH CHECKER
# =============================================================================

class HealthChecker:
    """
    Comprehensive health checker for all system components.
    
    Checks:
    - Database connectivity and latency
    - Redis cache connectivity
    - External API reachability (Google, Bing, NewsAPI)
    - LLM provider connectivity (OpenAI, Anthropic, Gemini)
    - System resources (CPU, memory, disk)
    """
    
    def __init__(self):
        """Initialize health checker."""
        self._start_time = datetime.now(UTC)
        self._version = os.environ.get("APP_VERSION", "1.0.0")
        logger.info("HealthChecker initialized")
    
    @property
    def uptime_seconds(self) -> float:
        """Get application uptime in seconds."""
        return (datetime.now(UTC) - self._start_time).total_seconds()
    
    # =========================================================================
    # COMPONENT CHECKS
    # =========================================================================
    
    async def check_database(self) -> ComponentHealth:
        """Check database connectivity and latency."""
        start = time.time()
        try:
            import os
            from pathlib import Path
            from src.storage.sqlite_article_repository import SqliteArticleRepository
            from src.storage.sqlite_engine import DEFAULT_CANONICAL_DB_PATH, SqliteEngine

            db_path_env = os.getenv("TECHNEWS_CANONICAL_DB_PATH") or os.getenv("CANONICAL_DB_PATH")
            db_path = Path(db_path_env) if db_path_env else DEFAULT_CANONICAL_DB_PATH

            engine = SqliteEngine(db_path)
            repo = SqliteArticleRepository(engine=engine, auto_init=False)
            count = await repo.count_articles()
            latency = (time.time() - start) * 1000
            
            return ComponentHealth(
                name="database",
                status="healthy",
                latency_ms=latency,
                details={
                    "type": "canonical_sqlite",
                    "article_count": count,
                }
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.warning(f"Database health check failed: {e}")
            return ComponentHealth(
                name="database",
                status="unhealthy",
                latency_ms=latency,
                error=str(e),
            )
    
    async def check_redis(self) -> ComponentHealth:
        """Check Redis connectivity."""
        start = time.time()
        try:
            from src.infrastructure.redis_event_bus import RedisEventBus
            bus = RedisEventBus()
            
            connected = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, bus.connect),
                timeout=5.0
            )
            latency = (time.time() - start) * 1000
            
            if connected:
                bus.disconnect()
                return ComponentHealth(
                    name="redis",
                    status="healthy",
                    latency_ms=latency,
                    details={"connected": True}
                )
            else:
                return ComponentHealth(
                    name="redis",
                    status="degraded",
                    latency_ms=latency,
                    details={"connected": False},
                    error="Could not connect to Redis"
                )
        except asyncio.TimeoutError:
            latency = (time.time() - start) * 1000
            return ComponentHealth(
                name="redis",
                status="degraded",
                latency_ms=latency,
                error="Connection timeout"
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            # Redis is optional, so mark as degraded not unhealthy
            return ComponentHealth(
                name="redis",
                status="degraded",
                latency_ms=latency,
                error=str(e)
            )
    
    async def check_external_apis(self) -> ComponentHealth:
        """Check external API reachability."""
        start = time.time()
        api_status = {}
        
        import aiohttp
        
        apis = {
            "google": "https://www.google.com",
            "bing": "https://www.bing.com",
            "duckduckgo": "https://duckduckgo.com",
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                for name, url in apis.items():
                    try:
                        async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            api_status[name] = {"reachable": resp.status < 400, "status_code": resp.status}
                    except Exception as e:
                        api_status[name] = {"reachable": False, "error": str(e)[:50]}
            
            latency = (time.time() - start) * 1000
            all_reachable = all(s.get("reachable", False) for s in api_status.values())
            
            return ComponentHealth(
                name="external_apis",
                status="healthy" if all_reachable else "degraded",
                latency_ms=latency,
                details=api_status
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return ComponentHealth(
                name="external_apis",
                status="degraded",
                latency_ms=latency,
                error=str(e)
            )
    
    async def check_llm_providers(self) -> ComponentHealth:
        """Check LLM provider API key availability."""
        start = time.time()
        providers = {}
        
        # Check for API keys in environment
        provider_keys = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
        }
        
        for provider, env_var in provider_keys.items():
            key = os.environ.get(env_var)
            providers[provider] = {
                "configured": bool(key),
                "key_prefix": key[:8] + "..." if key and len(key) > 8 else "not set"
            }
        
        latency = (time.time() - start) * 1000
        any_configured = any(p["configured"] for p in providers.values())
        
        return ComponentHealth(
            name="llm_providers",
            status="healthy" if any_configured else "degraded",
            latency_ms=latency,
            details=providers
        )
    
    def check_system_resources(self) -> ComponentHealth:
        """Check system resource usage."""
        start = time.time()
        
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            latency = (time.time() - start) * 1000
            
            # Determine status based on thresholds
            if memory.percent > 90 or disk.percent > 90:
                status = "unhealthy"
            elif memory.percent > 80 or disk.percent > 80:
                status = "degraded"
            else:
                status = "healthy"
            
            return ComponentHealth(
                name="system_resources",
                status=status,
                latency_ms=latency,
                details={
                    "cpu_percent": round(cpu_percent, 1),
                    "memory_percent": round(memory.percent, 1),
                    "memory_available_gb": round(memory.available / (1024**3), 2),
                    "disk_percent": round(disk.percent, 1),
                    "disk_free_gb": round(disk.free / (1024**3), 2),
                }
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            return ComponentHealth(
                name="system_resources",
                status="degraded",
                latency_ms=latency,
                error=str(e)
            )
    
    # =========================================================================
    # AGGREGATED CHECKS
    # =========================================================================
    
    async def check_all(self) -> SystemHealth:
        """Run all health checks and return aggregated status."""
        components = []
        
        # Run checks in parallel where possible
        db_health, redis_health, api_health, llm_health = await asyncio.gather(
            self.check_database(),
            self.check_redis(),
            self.check_external_apis(),
            self.check_llm_providers(),
            return_exceptions=True
        )
        
        # Add results (handling any exceptions)
        for health in [db_health, redis_health, api_health, llm_health]:
            if isinstance(health, Exception):
                components.append(ComponentHealth(
                    name="unknown",
                    status="unhealthy",
                    error=str(health)
                ))
            else:
                components.append(health)
        
        # Add synchronous check
        components.append(self.check_system_resources())
        
        # Determine overall status
        statuses = [c.status for c in components]
        if "unhealthy" in statuses:
            overall_status = "unhealthy"
        elif "degraded" in statuses:
            overall_status = "degraded"
        else:
            overall_status = "healthy"
        
        return SystemHealth(
            status=overall_status,
            components=components,
            uptime_seconds=self.uptime_seconds,
            version=self._version,
        )
    
    def check_liveness(self) -> dict:
        """Simple liveness check (is the app running?)."""
        return {
            "status": "ok",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    
    async def check_readiness(self) -> dict:
        """Readiness check (can the app accept traffic?)."""
        # Check critical components only
        db_health = await self.check_database()
        
        ready = db_health.status == "healthy"
        
        return {
            "ready": ready,
            "timestamp": datetime.now(UTC).isoformat(),
            "checks": {
                "database": db_health.status,
            }
        }


# =============================================================================
# SINGLETON
# =============================================================================

_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """Get singleton HealthChecker instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker
