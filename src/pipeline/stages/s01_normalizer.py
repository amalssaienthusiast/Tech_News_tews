"""
Stage 1: Observation Normalizer.
Location: src/pipeline/stages/s01_normalizer.py

Transforms raw SourceObservation into canonical NormalizedArticle:
- Canonicalizes URL (strips tracking query params, default ports, anchors)
- Preserves original observed URL
- Cleans HTML entities, tags, and irregular whitespace from title & summary
- Enforces timezone-aware UTC datetimes
- Preserves source provenance, tier, and species
"""

from __future__ import annotations

from datetime import datetime, UTC
import html
import logging
import re
import time
from typing import Any, Dict, Optional

from ...domain.models import SourceObservation, NormalizedArticle
from ...domain.validators import canonicalize_url, validate_non_empty_string, validate_utc_datetime, DomainValidationError
from ..protocols import PipelineStage, PipelineContext

logger = logging.getLogger(__name__)

HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_headline_text(raw_title: str) -> str:
    """
    Clean headline string:
    - Decodes HTML entities (&amp; -> &, &#8217; -> ', etc.)
    - Normalizes typographic quotes (curly single/double quotes to standard ASCII)
    - Strips HTML tags (<b>, <span>, etc.)
    - Collapses multiple whitespace/newlines into a single space
    - Strips leading/trailing whitespace
    """
    if not raw_title or not isinstance(raw_title, str) or not raw_title.strip():
        raise DomainValidationError("Title must be a non-empty string")

    # Decode HTML entities twice in case of double-escaped entities
    decoded = html.unescape(html.unescape(raw_title))
    # Normalize typographic quotes
    normalized_quotes = (
        decoded.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2014", " - ")
        .replace("\u2013", " - ")
    )
    # Strip HTML tags
    stripped_tags = HTML_TAG_PATTERN.sub(" ", normalized_quotes)
    # Collapse whitespace
    cleaned = WHITESPACE_PATTERN.sub(" ", stripped_tags).strip()

    if len(cleaned) < 3:
        raise DomainValidationError(f"Cleaned title '{cleaned}' is too short (min 3 chars)")

    return cleaned


def clean_summary_text(raw_summary: str) -> str:
    """Clean summary/excerpt text of HTML tags and irregular whitespace."""
    if not raw_summary or not isinstance(raw_summary, str):
        return ""
    decoded = html.unescape(html.unescape(raw_summary))
    stripped_tags = HTML_TAG_PATTERN.sub(" ", decoded)
    return WHITESPACE_PATTERN.sub(" ", stripped_tags).strip()


class ObservationNormalizer:
    """
    Stage 1 Normalizer: Implements PipelineStage[SourceObservation, NormalizedArticle].
    """

    @property
    def name(self) -> str:
        return "observation_normalizer"

    @property
    def stage_number(self) -> int:
        return 1

    async def process(
        self,
        input_item: SourceObservation,
        context: PipelineContext,
    ) -> Optional[NormalizedArticle]:
        """
        Process a single SourceObservation into a NormalizedArticle.
        """
        start_time = time.perf_counter()

        if not isinstance(input_item, SourceObservation):
            raise DomainValidationError(f"ObservationNormalizer expects SourceObservation, got {type(input_item)}")

        # 1. Canonicalize URL
        canonical_url = canonicalize_url(input_item.url)

        # 2. Clean Title & Summary
        clean_title = clean_headline_text(input_item.title)
        clean_summary = clean_summary_text(input_item.summary)

        # 3. Handle Timestamps (enforce UTC)
        discovered_at = input_item.observed_at or datetime.now(UTC)
        if discovered_at.tzinfo is None:
            discovered_at = discovered_at.replace(tzinfo=UTC)

        published_at = input_item.published_at_hint
        if published_at is not None and published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)

        # 4. Prepare Metadata & Tags
        metadata = dict(input_item.metadata)
        tags = metadata.get("tags")
        authors = metadata.get("authors")

        # 5. Construct Canonical NormalizedArticle
        normalized = NormalizedArticle.create(
            canonical_url=canonical_url,
            original_url=input_item.url,
            title=clean_title,
            clean_text=input_item.raw_content or "",
            summary=clean_summary,
            source_id=input_item.source_id,
            source_name=input_item.source_name,
            source_tier=input_item.source_tier,
            zombie_species=input_item.zombie_species,
            discovered_at=discovered_at,
            published_at=published_at,
            image_url=input_item.image_url,
            authors=authors,
            tags=tags,
            metadata=metadata,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        context.record_metric(self.name, elapsed_ms)

        return normalized
