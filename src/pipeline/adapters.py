"""
Ingestion Adapters for Canonical Domain Contracts.
Location: src/pipeline/adapters.py

Converts legacy ingestion models (EventSource, SourceDescriptor, Article, raw dicts)
into the approved canonical SourceObservation contract (Phase 2B / 3A).
Fails explicitly on invalid or incomplete inputs; never silently fabricates critical data.
"""

from __future__ import annotations

from datetime import datetime, UTC
import logging
from typing import Any, Dict, Optional, Union

from ..domain.enums import SourceTier, ZombieSpecies
from ..domain.models import SourceObservation
from ..domain.validators import DomainValidationError, validate_non_empty_string

logger = logging.getLogger(__name__)


def _normalize_utc_datetime(val: Any) -> Optional[datetime]:
    """Coerce various datetime representations to timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=UTC)
        return val.astimezone(UTC)
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=UTC)
    if isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            return None
        try:
            # Handle ISO format strings (including Z suffix)
            if val_str.endswith("Z"):
                val_str = val_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(val_str)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except (ValueError, TypeError) as e:
            raise DomainValidationError(f"Invalid timestamp string '{val}': {e}")
    raise DomainValidationError(f"Unsupported timestamp type: {type(val)}")


def _resolve_source_tier(tier_val: Any) -> SourceTier:
    """Resolve various tier representations to canonical SourceTier."""
    if tier_val is None:
        return SourceTier.TIER_3_COMMUNITY
    if isinstance(tier_val, SourceTier):
        return tier_val
    if isinstance(tier_val, int):
        tier_map = {
            1: SourceTier.TIER_1_PREMIUM,
            2: SourceTier.TIER_2_SPECIALIST,
            3: SourceTier.TIER_3_COMMUNITY,
            4: SourceTier.TIER_4_DISCOVERY,
        }
        if tier_val in tier_map:
            return tier_map[tier_val]
        raise DomainValidationError(f"Invalid source tier integer '{tier_val}'. Must be 1-4.")
    if hasattr(tier_val, "value"):
        return _resolve_source_tier(tier_val.value)
    if isinstance(tier_val, str):
        tier_str = tier_val.strip().upper()
        if tier_str in ("1", "TIER_1", "TIER_1_PREMIUM"):
            return SourceTier.TIER_1_PREMIUM
        if tier_str in ("2", "TIER_2", "TIER_2_SPECIALIST"):
            return SourceTier.TIER_2_SPECIALIST
        if tier_str in ("3", "TIER_3", "TIER_3_COMMUNITY"):
            return SourceTier.TIER_3_COMMUNITY
        if tier_str in ("4", "TIER_4", "TIER_4_DISCOVERY"):
            return SourceTier.TIER_4_DISCOVERY
    raise DomainValidationError(f"Cannot resolve SourceTier from: {tier_val}")


def _resolve_zombie_species(species_val: Any) -> ZombieSpecies:
    """Resolve various zombie species representations to canonical ZombieSpecies."""
    if species_val is None:
        return ZombieSpecies.RSS
    if isinstance(species_val, ZombieSpecies):
        return species_val
    if hasattr(species_val, "value"):
        species_val = species_val.value
    if isinstance(species_val, str):
        s_clean = species_val.strip().lower()
        species_map = {
            "z_rss": ZombieSpecies.RSS,
            "rss": ZombieSpecies.RSS,
            "z_github": ZombieSpecies.GITHUB,
            "github": ZombieSpecies.GITHUB,
            "z_hacker": ZombieSpecies.HACKER_NEWS,
            "hacker_news": ZombieSpecies.HACKER_NEWS,
            "hackernews": ZombieSpecies.HACKER_NEWS,
            "hn": ZombieSpecies.HACKER_NEWS,
            "z_security": ZombieSpecies.SECURITY,
            "security": ZombieSpecies.SECURITY,
            "nvd": ZombieSpecies.SECURITY,
            "cve": ZombieSpecies.SECURITY,
            "z_corp": ZombieSpecies.CORPORATE,
            "corporate": ZombieSpecies.CORPORATE,
            "corp": ZombieSpecies.CORPORATE,
            "z_web": ZombieSpecies.WEB,
            "web": ZombieSpecies.WEB,
            "z_discovery": ZombieSpecies.DISCOVERY,
            "discovery": ZombieSpecies.DISCOVERY,
        }
        if s_clean in species_map:
            return species_map[s_clean]
    raise DomainValidationError(f"Cannot resolve ZombieSpecies from: {species_val}")


class SourceObservationAdapter:
    """
    Adapter converting legacy ingestion data structures into canonical SourceObservation models.
    """

    @staticmethod
    def from_event_source(source: Any) -> SourceObservation:
        """
        Convert legacy EventSource dataclass to canonical SourceObservation.
        """
        if not hasattr(source, "url") or not hasattr(source, "title"):
            raise DomainValidationError("Input object is not an EventSource representation")

        url = getattr(source, "url", "")
        title = getattr(source, "title", "")
        source_name = getattr(source, "source_name", "")
        source_id = getattr(source, "article_id", "") or getattr(source, "source_id", "") or source_name

        validate_non_empty_string(url, "url")
        validate_non_empty_string(title, "title")
        validate_non_empty_string(source_name, "source_name")

        tier = _resolve_source_tier(getattr(source, "source_tier", None))
        species = _resolve_zombie_species(getattr(source, "zombie_species", None))
        published_at = _normalize_utc_datetime(getattr(source, "published_at", None))
        observed_at = _normalize_utc_datetime(getattr(source, "discovered_at", None)) or datetime.now(UTC)

        metadata: Dict[str, Any] = {}
        if getattr(source, "is_primary", False):
            metadata["is_primary"] = True

        return SourceObservation.create(
            source_id=source_id,
            source_name=source_name,
            source_tier=tier,
            zombie_species=species,
            url=url,
            title=title,
            raw_content="",
            summary=getattr(source, "summary", "") or "",
            image_url=getattr(source, "image_url", None),
            published_at_hint=published_at,
            observed_at=observed_at,
            metadata=metadata,
        )

    @staticmethod
    def from_source_descriptor(
        descriptor: Any,
        title: str,
        url: Optional[str] = None,
        raw_content: str = "",
        summary: str = "",
        published_at: Optional[datetime] = None,
        image_url: Optional[str] = None,
        zombie_species: Optional[Union[ZombieSpecies, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SourceObservation:
        """
        Convert SourceDescriptor + scraped item attributes to canonical SourceObservation.
        """
        source_id = getattr(descriptor, "id", "")
        source_name = getattr(descriptor, "name", "")
        resolved_url = url or getattr(descriptor, "url", "")

        validate_non_empty_string(source_id, "descriptor.id")
        validate_non_empty_string(source_name, "descriptor.name")
        validate_non_empty_string(resolved_url, "url")
        validate_non_empty_string(title, "title")

        tier = _resolve_source_tier(getattr(descriptor, "tier", None))
        species = _resolve_zombie_species(zombie_species)
        published_dt = _normalize_utc_datetime(published_at)

        merged_metadata = dict(metadata or {})
        if hasattr(descriptor, "type"):
            dtype = getattr(descriptor.type, "value", str(descriptor.type))
            merged_metadata["source_type"] = dtype

        return SourceObservation.create(
            source_id=source_id,
            source_name=source_name,
            source_tier=tier,
            zombie_species=species,
            url=resolved_url,
            title=title,
            raw_content=raw_content,
            summary=summary,
            image_url=image_url,
            published_at_hint=published_dt,
            metadata=merged_metadata,
        )

    @staticmethod
    def from_legacy_article(
        article: Any,
        zombie_species: Optional[Union[ZombieSpecies, str]] = None,
    ) -> SourceObservation:
        """
        Convert legacy Article (from src/core/types.py) to canonical SourceObservation.
        """
        url = getattr(article, "url", "")
        title = getattr(article, "title", "")
        source_name = getattr(article, "source", "") or getattr(article, "source_name", "")
        article_id = getattr(article, "id", "") or source_name

        validate_non_empty_string(url, "article.url")
        validate_non_empty_string(title, "article.title")
        validate_non_empty_string(source_name, "article.source")

        tier = _resolve_source_tier(getattr(article, "source_tier", None))
        species = _resolve_zombie_species(zombie_species)
        published_dt = _normalize_utc_datetime(getattr(article, "published_at", None))
        observed_dt = _normalize_utc_datetime(getattr(article, "scraped_at", None)) or datetime.now(UTC)

        metadata: Dict[str, Any] = {}
        if getattr(article, "category", None):
            metadata["category"] = article.category
        if getattr(article, "pipeline", None):
            metadata["pipeline"] = article.pipeline
        if getattr(article, "keywords", None):
            metadata["keywords"] = list(article.keywords)
        if getattr(article, "entities", None):
            metadata["entities"] = dict(article.entities)

        return SourceObservation.create(
            source_id=article_id,
            source_name=source_name,
            source_tier=tier,
            zombie_species=species,
            url=url,
            title=title,
            raw_content=getattr(article, "content", "") or "",
            summary=getattr(article, "summary", "") or "",
            image_url=getattr(article, "image_url", None),
            published_at_hint=published_dt,
            observed_at=observed_dt,
            metadata=metadata,
        )

    @staticmethod
    def from_raw_dict(data: Dict[str, Any]) -> SourceObservation:
        """
        Convert raw dictionary payload (e.g. from crawler/scraper) to canonical SourceObservation.
        """
        if not isinstance(data, dict):
            raise DomainValidationError(f"Expected dict input, got {type(data)}")

        url = data.get("url", "")
        title = data.get("title", "")
        source_name = data.get("source_name") or data.get("source") or ""
        source_id = data.get("source_id") or data.get("article_id") or source_name

        validate_non_empty_string(url, "data.url")
        validate_non_empty_string(title, "data.title")
        validate_non_empty_string(source_name, "data.source_name")

        tier = _resolve_source_tier(data.get("source_tier") or data.get("tier"))
        species = _resolve_zombie_species(data.get("zombie_species") or data.get("species"))
        published_dt = _normalize_utc_datetime(data.get("published_at") or data.get("published_at_hint"))
        observed_dt = _normalize_utc_datetime(data.get("observed_at") or data.get("discovered_at") or data.get("scraped_at")) or datetime.now(UTC)

        raw_content = data.get("raw_content") or data.get("content") or ""
        summary = data.get("summary") or ""
        image_url = data.get("image_url")
        headers = data.get("headers")
        metadata = data.get("metadata")

        return SourceObservation.create(
            source_id=str(source_id),
            source_name=str(source_name),
            source_tier=tier,
            zombie_species=species,
            url=str(url),
            title=str(title),
            raw_content=str(raw_content),
            summary=str(summary),
            image_url=str(image_url) if image_url else None,
            published_at_hint=published_dt,
            observed_at=observed_dt,
            headers=headers,
            metadata=metadata,
        )
