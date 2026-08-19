"""Discovery package - combines web discovery and global geo-rotation."""

import importlib.util
import sys
from pathlib import Path

# Load WebDiscoveryAgent from sibling module `src/discovery.py`.
_discovery_py = Path(__file__).parent.parent / "discovery.py"
spec = importlib.util.spec_from_file_location("_discovery_module", _discovery_py)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load discovery module from {_discovery_py}")
_discovery_module = importlib.util.module_from_spec(spec)
sys.modules["_discovery_module"] = _discovery_module
spec.loader.exec_module(_discovery_module)
_BaseWebDiscoveryAgent = _discovery_module.WebDiscoveryAgent
GOOGLE_API_KEY = _discovery_module.GOOGLE_API_KEY
GOOGLE_CSE_ID = _discovery_module.GOOGLE_CSE_ID
BING_API_KEY = _discovery_module.BING_API_KEY


class WebDiscoveryAgent(_BaseWebDiscoveryAgent):
    """Compatibility wrapper that syncs patched package-level API keys."""

    def __init__(self, db=None):
        # Keep underlying module-level API key values in sync so patching
        # `src.discovery.GOOGLE_API_KEY` in tests affects behavior.
        _discovery_module.GOOGLE_API_KEY = GOOGLE_API_KEY
        _discovery_module.GOOGLE_CSE_ID = GOOGLE_CSE_ID
        _discovery_module.BING_API_KEY = BING_API_KEY
        if db is None:
            class _DefaultStore:
                def __init__(self):
                    self.discovered_sources = []

                def add_discovered_source(self, source_info):
                    self.discovered_sources.append(source_info)
                    return True

            db = _DefaultStore()
        super().__init__(db)


class DiscoveryAgent(WebDiscoveryAgent):
    """Backward-compatible alias used by legacy tests and callers."""

    def __init__(self, db=None):
        if db is None:
            class _DefaultStore:
                def __init__(self):
                    self.discovered_sources = []

                def add_discovered_source(self, source_info):
                    self.discovered_sources.append(source_info)
                    return True

            db = _DefaultStore()
        super().__init__(db)

# Import from global_discovery.py (in this package)
from .global_discovery import (
    TechHub,
    TECH_HUBS,
    GlobalDiscoveryManager,
    get_global_discovery_manager,
)

# Import lifecycle FSM
from .lifecycle import (
    DiscoveredSourceRecord,
    DiscoveryLifecycleManager,
    DiscoveryState,
    InvalidDiscoveryTransitionError,
)

__all__ = [
    "WebDiscoveryAgent",  # Original web discovery
    "DiscoveryAgent",
    "GOOGLE_API_KEY",
    "GOOGLE_CSE_ID",
    "BING_API_KEY",
    "TechHub",
    "TECH_HUBS", 
    "GlobalDiscoveryManager",
    "get_global_discovery_manager",
    "DiscoveryState",
    "DiscoveredSourceRecord",
    "DiscoveryLifecycleManager",
    "InvalidDiscoveryTransitionError",
]
