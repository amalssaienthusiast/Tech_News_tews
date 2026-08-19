"""
Unified Configuration Manager for gui_qt.

Provides centralised management of all system settings with
persistent storage, change-notification callbacks, and
import / export.  Fully framework-agnostic (no Tkinter deps).
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SystemConfig:
    """System-wide configuration."""
    max_concurrent_scrapes: int = 5
    request_timeout_seconds: int = 30
    enable_cache: bool = True
    cache_ttl_seconds: int = 300
    log_level: str = "INFO"
    auto_start_feed: bool = True


@dataclass
class AIConfig:
    """AI subsystem configuration."""
    primary_provider: str = "gemini"
    default_model: str = "gemini-pro"
    daily_cost_limit_usd: float = 10.0
    enable_summaries: bool = True
    enable_sentiment: bool = True
    cache_responses: bool = True


@dataclass
class BypassConfig:
    """Bypass engine configuration."""
    enable_stealth: bool = True
    enable_proxy_rotation: bool = False
    max_retries: int = 3
    backoff_factor: float = 1.5
    user_agent_rotation: bool = True
    respect_robots_txt: bool = True


@dataclass
class ResilienceConfig:
    """Resilience system configuration."""
    enable_auto_fix: bool = True
    enable_monitoring: bool = True
    health_check_interval_seconds: int = 300
    max_issues_before_alert: int = 5
    enable_deprecation_warnings: bool = True


@dataclass
class UserConfig:
    """User preference configuration."""
    theme_variant: str = "user"
    articles_per_page: int = 20
    enable_notifications: bool = True
    auto_refresh_interval_seconds: int = 300
    show_ai_summaries: bool = True
    compact_mode: bool = False


@dataclass
class UnifiedConfig:
    """Complete unified configuration."""
    system: SystemConfig = field(default_factory=SystemConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    bypass: BypassConfig = field(default_factory=BypassConfig)
    resilience: ResilienceConfig = field(default_factory=ResilienceConfig)
    user: UserConfig = field(default_factory=UserConfig)
    last_modified: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system": asdict(self.system),
            "ai": asdict(self.ai),
            "bypass": asdict(self.bypass),
            "resilience": asdict(self.resilience),
            "user": asdict(self.user),
            "last_modified": self.last_modified,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedConfig":
        return cls(
            system=SystemConfig(**data.get("system", {})),
            ai=AIConfig(**data.get("ai", {})),
            bypass=BypassConfig(**data.get("bypass", {})),
            resilience=ResilienceConfig(**data.get("resilience", {})),
            user=UserConfig(**data.get("user", {})),
            last_modified=data.get("last_modified", ""),
        )


# ---------------------------------------------------------------------------
# Configuration manager
# ---------------------------------------------------------------------------

class UnifiedConfiguration:
    """
    Central configuration management for all modules.

    Persistent storage: ``~/.technews/unified_config.json``

    Usage::

        cfg = get_config()
        timeout = cfg.get("system.request_timeout_seconds")
        cfg.set("ai.enable_summaries", False)
        cfg.on_change("system", my_handler)
    """

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".technews"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "unified_config.json"

        self._config = UnifiedConfig()
        self._change_callbacks: Dict[str, List[Callable]] = {
            "system": [], "ai": [], "bypass": [],
            "resilience": [], "user": [], "*": [],
        }
        self._load()
        logger.info("UnifiedConfiguration loaded from %s", self.config_file)

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        try:
            if self.config_file.exists():
                with open(self.config_file) as fh:
                    self._config = UnifiedConfig.from_dict(json.load(fh))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load config: %s — using defaults", exc)
            self._config = UnifiedConfig()

    def _save(self) -> None:
        try:
            self._config.last_modified = datetime.now(timezone.utc).isoformat()
            with open(self.config_file, "w") as fh:
                json.dump(self._config.to_dict(), fh, indent=2)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not save config: %s", exc)

    # -- accessors -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        try:
            obj: Any = self._config
            for part in key.split("."):
                obj = getattr(obj, part)
            return obj
        except (AttributeError, TypeError):
            return default

    def set(self, key: str, value: Any, *, save: bool = True) -> bool:
        parts = key.split(".")
        if len(parts) < 2:
            return False
        section, attr = parts[0], parts[1]
        section_obj = getattr(self._config, section, None)
        if section_obj is None or not hasattr(section_obj, attr):
            return False
        setattr(section_obj, attr, value)
        if save:
            self._save()
        self._notify_change(section, attr, value)
        return True

    def get_section(self, section: str) -> Any:
        return getattr(self._config, section, None)

    # -- change callbacks ----------------------------------------------------

    def on_change(self, section: str, callback: Callable[[str, Any], None]) -> None:
        if section in self._change_callbacks:
            self._change_callbacks[section].append(callback)

    def _notify_change(self, section: str, attr: str, value: Any) -> None:
        for cb in self._change_callbacks.get(section, []):
            try:
                cb(attr, value)
            except Exception as exc:  # noqa: BLE001
                logger.error("Config callback error: %s", exc)
        for cb in self._change_callbacks.get("*", []):
            try:
                cb(f"{section}.{attr}", value)
            except Exception as exc:  # noqa: BLE001
                logger.error("Global config callback error: %s", exc)

    # -- import / export / reset ---------------------------------------------

    def export_config(self, filepath: Path) -> bool:
        try:
            with open(filepath, "w") as fh:
                json.dump(self._config.to_dict(), fh, indent=2)
            logger.info("Configuration exported to %s", filepath)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Export failed: %s", exc)
            return False

    def import_config(self, filepath: Path) -> bool:
        try:
            with open(filepath) as fh:
                data = json.load(fh)
            self._config = UnifiedConfig.from_dict(data)
            self._save()
            for section in ("system", "ai", "bypass", "resilience", "user"):
                self._notify_change(section, "*", getattr(self._config, section))
            logger.info("Configuration imported from %s", filepath)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Import failed: %s", exc)
            return False

    def reset_to_defaults(self, section: Optional[str] = None) -> None:
        _defaults = {
            "system": SystemConfig, "ai": AIConfig, "bypass": BypassConfig,
            "resilience": ResilienceConfig, "user": UserConfig,
        }
        if section and section in _defaults:
            setattr(self._config, section, _defaults[section]())
            self._notify_change(section, "*", getattr(self._config, section))
        else:
            self._config = UnifiedConfig()
            for s in _defaults:
                self._notify_change(s, "*", getattr(self._config, s))
        self._save()

    def get_config_summary(self) -> Dict[str, Any]:
        return {
            "last_modified": self._config.last_modified,
            "sections": self._config.to_dict(),
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_config_manager: Optional[UnifiedConfiguration] = None


def get_config() -> UnifiedConfiguration:
    """Return the global configuration manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = UnifiedConfiguration()
    return _config_manager
