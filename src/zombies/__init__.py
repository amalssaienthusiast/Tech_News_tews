"""
Zombie Acquisition Layer — Autonomous crawler swarm and specialized collectors.
"""

from .zombie_base import ZombieBase, ObservationIngestionCallback
from .z_rss import ZRss
from .z_web import ZWeb
from .z_corp import ZCorp
from .z_hacker import ZHacker
from .z_github import ZGitHub
from .z_security import ZSecurity
from .coordinator import (
    LeaseResult,
    LeaseStatus,
    LocalSwarmCoordinator,
    SqliteSwarmCoordinator,
    SwarmCoordinatorProtocol,
)
from .swarm import ZombieSwarm, SourceObservationIngestionCallback

__all__ = [
    "ZombieBase",
    "ObservationIngestionCallback",
    "ZRss",
    "ZWeb",
    "ZCorp",
    "ZHacker",
    "ZGitHub",
    "ZSecurity",
    "ZombieSwarm",
    "SourceObservationIngestionCallback",
    "SwarmCoordinatorProtocol",
    "LocalSwarmCoordinator",
    "SqliteSwarmCoordinator",
    "LeaseResult",
    "LeaseStatus",
]
