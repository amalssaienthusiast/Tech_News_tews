"""
Global Discovery Manager - Phase 1: Geo-Rotation System
Implements TECH_HUBS rotation for global news coverage
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import random

logger = logging.getLogger(__name__)

@dataclass
class TechHub:
    """Represents a global technology hub for news discovery"""
    code: str  # ISO country code (e.g., 'US', 'IN', 'JP')
    language: str  # Language code (e.g., 'en', 'ja', 'zh-CN')
    name: str  # Human-readable name
    timezone: str  # Primary timezone
    priority: int = 5  # Priority level (1-10, higher = more important)
    topics: List[str] = None  # Region-specific topics
    
    def __post_init__(self):
        if self.topics is None:
            self.topics = []


# Global Technology Hubs Configuration
TECH_HUBS = [
    # Tier 1: Major Tech Centers (High Priority)
    TechHub("US", "en", "United States (Silicon Valley)", "America/Los_Angeles", 10, 
            ["AI", "Startups", "Venture Capital", "Big Tech"]),
    TechHub("CN", "zh-CN", "China (Shenzhen/Beijing)", "Asia/Shanghai", 10,
            ["AI", "Hardware", "5G", "Electric Vehicles"]),
    TechHub("IN", "en", "India (Bangalore/Hyderabad)", "Asia/Kolkata", 9,
            ["Software", "IT Services", "Startups", "AI"]),
    
    # Tier 2: Major Markets (Medium-High Priority)
    TechHub("GB", "en", "United Kingdom (London)", "Europe/London", 8,
            ["Fintech", "AI", "Startups"]),
    TechHub("DE", "de", "Germany (Berlin/Munich)", "Europe/Berlin", 8,
            ["Engineering", "Industrial Tech", "AI"]),
    TechHub("JP", "ja", "Japan (Tokyo)", "Asia/Tokyo", 8,
            ["Robotics", "Hardware", "AI", "Gaming"]),
    TechHub("KR", "ko", "South Korea (Seoul)", "Asia/Seoul", 8,
            ["Samsung", "Semiconductors", "5G", "Gaming"]),
    
    # Tier 3: Emerging Hubs (Medium Priority)
    TechHub("IL", "en", "Israel (Tel Aviv)", "Asia/Jerusalem", 7,
            ["Cybersecurity", "AI", "Startups"]),
    TechHub("SG", "en", "Singapore", "Asia/Singapore", 7,
            ["Fintech", "Smart Cities", "AI"]),
    TechHub("AU", "en", "Australia (Sydney)", "Australia/Sydney", 6,
            ["Mining Tech", "Clean Energy", "AI"]),
    TechHub("CA", "en", "Canada (Toronto/Vancouver)", "America/Toronto", 6,
            ["AI", "Clean Tech", "Startups"]),
    TechHub("FR", "fr", "France (Paris)", "Europe/Paris", 6,
            ["AI", "Aerospace", "Nuclear Tech"]),
    TechHub("BR", "pt", "Brazil (São Paulo)", "America/Sao_Paulo", 5,
            ["Fintech", "Agtech", "Startups"]),
    
    # Tier 4: Specialized Regions (Lower Priority but Important)
    TechHub("TW", "zh-TW", "Taiwan (Taipei)", "Asia/Taipei", 7,
            ["Semiconductors", "Hardware", "Electronics"]),
    TechHub("SE", "sv", "Sweden (Stockholm)", "Europe/Stockholm", 6,
            ["Gaming", "Clean Tech", "5G"]),
    TechHub("CH", "de", "Switzerland (Zurich)", "Europe/Zurich", 5,
            ["Biotech", "Fintech", "Precision Engineering"]),
    TechHub("NL", "nl", "Netherlands (Amsterdam)", "Europe/Amsterdam", 5,
            ["Agtech", "Smart Cities", "Fintech"]),
    TechHub("AE", "en", "UAE (Dubai)", "Asia/Dubai", 5,
            ["Smart Cities", "Blockchain", "AI"]),
    TechHub("RU", "ru", "Russia (Moscow)", "Europe/Moscow", 4,
            ["Cybersecurity", "Space Tech", "AI"]),
]


class GlobalDiscoveryManager:
    """
    Manages global news discovery across multiple regions.
    Implements rotating geo-targeted searches for comprehensive coverage.
    """
    
    def __init__(self, rotation_interval: int = 120):
        """
        Initialize global discovery manager.
        
        Args:
            rotation_interval: Seconds between region rotations (default: 120)
        """

        self.hubs = TECH_HUBS
        self.rotation_interval = rotation_interval
        self.current_hub_index = 0
        self.last_rotation = datetime.now()
        self.discovery_stats: Dict[str, int] = {}  # hub_code -> article_count
        self.on_new_region: Optional[Callable[[TechHub], None]] = None
        self._running = False
        self._rotation_task: Optional[asyncio.Task] = None
        
        # Priority-weighted selection
        self._setup_priority_weights()
        
        logger.info(f"🌍 Global Discovery Manager initialized")
        logger.info(f"   {len(self.hubs)} tech hubs configured")
        logger.info(f"   Rotation interval: {rotation_interval}s")
        
    def _setup_priority_weights(self):
        """Setup weighted selection based on hub priority"""
        total_priority = sum(hub.priority for hub in self.hubs)
        self.hub_weights = [hub.priority / total_priority for hub in self.hubs]
        
    async def start(self):
        """Start the rotation loop"""
        self._running = True
        self._rotation_task = asyncio.create_task(self._rotation_loop())
        logger.info("🌍 Global discovery rotation started")
        
    async def stop(self):
        """Stop the rotation loop"""
        self._running = False
        if self._rotation_task:
            self._rotation_task.cancel()
            try:
                await self._rotation_task
            except asyncio.CancelledError:
                pass
        logger.info("🌍 Global discovery rotation stopped")
        
    async def _rotation_loop(self):
        """Main rotation loop - cycles through tech hubs"""
        while self._running:
            try:
                # Get current hub and rotate
                hub = self.get_current_hub()
                
                # Log rotation
                logger.info(f"🌍 Rotating to {hub.name} ({hub.code})")
                
                # Notify callback if registered
                if self.on_new_region:
                    try:
                        if asyncio.iscoroutinefunction(self.on_new_region):
                            await self.on_new_region(hub)
                        else:
                            self.on_new_region(hub)
                    except Exception as e:
                        logger.error(f"Error in region callback: {e}")
                
                # Wait for rotation interval
                await asyncio.sleep(self.rotation_interval)
                
                # Move to next hub
                self._rotate_to_next()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in rotation loop: {e}")
                await asyncio.sleep(5)  # Wait before retry
                
    def _rotate_to_next(self):
        """Rotate to next hub (weighted random selection)"""
        # Use weighted random selection based on priority
        import random
        self.current_hub_index = random.choices(
            range(len(self.hubs)), 
            weights=self.hub_weights, 
            k=1
        )[0]
        self.last_rotation = datetime.now()
        
    def get_current_hub(self) -> TechHub:
        """Get the currently active tech hub"""
        return self.hubs[self.current_hub_index]
        
    def get_next_hubs(self, count: int = 5) -> List[TechHub]:
        """Get the next N hubs in rotation sequence"""
        hubs = []
        idx = self.current_hub_index
        for _ in range(count):
            idx = (idx + 1) % len(self.hubs)
            hubs.append(self.hubs[idx])
        return hubs
        
    def get_hub_by_code(self, code: str) -> Optional[TechHub]:
        """Get hub configuration by country code"""
        for hub in self.hubs:
            if hub.code.upper() == code.upper():
                return hub
        return None
        
    def update_stats(self, hub_code: str, article_count: int):
        """Update discovery statistics for a hub"""
        if hub_code not in self.discovery_stats:
            self.discovery_stats[hub_code] = 0
        self.discovery_stats[hub_code] += article_count
        
    def get_stats(self) -> Dict:
        """Get discovery statistics"""
        return {
            "total_hubs": len(self.hubs),
            "current_hub": self.get_current_hub().code,
            "articles_by_region": self.discovery_stats,
            "total_articles": sum(self.discovery_stats.values()),
            "last_rotation": self.last_rotation.isoformat(),
        }
        
    def get_search_params(self) -> Dict[str, str]:
        """
        Get search parameters for current hub.
        Returns dict with 'gl' and 'hl' for Google/Bing APIs.
        """
        hub = self.get_current_hub()
        return {
            "gl": hub.code,  # Geographic location
            "hl": hub.language,  # Language
            "cr": f"country{hub.code}",  # Country restriction
        }


# Global singleton instance
_global_discovery_manager: Optional[GlobalDiscoveryManager] = None


def get_global_discovery_manager(rotation_interval: int = 120) -> GlobalDiscoveryManager:
    """Get or create global discovery manager singleton"""
    global _global_discovery_manager
    if _global_discovery_manager is None:
        _global_discovery_manager = GlobalDiscoveryManager(rotation_interval)
    return _global_discovery_manager


# Example usage
if __name__ == "__main__":
    async def test():
        manager = get_global_discovery_manager(rotation_interval=10)
        
        # Set up callback
        async def on_region(hub: TechHub):
            print(f"\n🌍 Now scanning: {hub.name}")
            print(f"   Topics: {', '.join(hub.topics)}")
            print(f"   Search params: {manager.get_search_params()}")
        
        manager.on_new_region = on_region
        
        # Start rotation
        await manager.start()
        
        # Run for 60 seconds
        await asyncio.sleep(60)
        
        # Stop and show stats
        await manager.stop()
        print("\n📊 Discovery Stats:")
        print(manager.get_stats())
    
    asyncio.run(test())
