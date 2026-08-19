"""
DedupGate - Two-Tier Persistent Deduplication Engine.

Tier 1: O(1) Bloom Filter check on canonicalized URLs.
Tier 2: MinHash / LSH similarity check on 3-word title shingles for Bloom hits.
Persistence: SQLite storage in cache/dedup_state.sqlite to prevent duplicate bursts across restarts.
"""

from dataclasses import dataclass
import hashlib
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
from typing import List, Set, Tuple, Optional
from urllib.parse import urlparse, parse_qsl, urlunparse, urlencode

from ..core.types import Article

logger = logging.getLogger(__name__)

DB_PATH = Path("cache/dedup_state.sqlite")
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "igshid", "mc_eid", "_ga", "_hsenc", "_openstat"
}

def canonicalize_url(url: str) -> str:
    """
    Canonicalize URL for deduplication:
    - Lowercase scheme and netloc
    - Strip tracking parameters (utm_*, ref, fbclid, etc.)
    - Sort remaining query parameters
    - Strip trailing slashes and default ports
    """
    if not url:
        return ""
    
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        elif netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]

        path = parsed.path.rstrip("/")
        if not path:
            path = ""

        # Filter out tracking parameters and sort remaining query params
        query_params = parse_qsl(parsed.query, keep_blank_values=False)
        filtered_params = sorted([(k, v) for k, v in query_params if k.lower() not in TRACKING_PARAMS])
        query = urlencode(filtered_params)

        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception as e:
        logger.debug(f"URL canonicalization error for '{url}': {e}")
        return url.strip().lower()


def normalize_title(title: str) -> str:
    """Normalize article title for MinHash shingling."""
    if not title:
        return ""
    # Lowercase and remove punctuation except alphanumeric and spaces
    clean = re.sub(r'[^\w\s]', '', title.lower())
    return ' '.join(clean.split())


def get_shingles(text: str, k: int = 3) -> List[str]:
    """Generate k-word shingles from text."""
    words = text.split()
    if len(words) < k:
        return [' '.join(words)] if words else []
    return [' '.join(words[i:i+k]) for i in range(len(words) - k + 1)]


class MinHash:
    """Simple 64-hash MinHash implementation for text similarity."""
    NUM_PERMUTATIONS = 64
    PRIME = (1 << 61) - 1

    def __init__(self, num_perm: int = 64):
        self.num_perm = num_perm
        # Deterministic seed coefficients for hash functions: h(x) = (a * x + b) % PRIME
        self._a = [((i + 1) * 2654435761) % self.PRIME for i in range(self.num_perm)]
        self._b = [((i + 1) * 1597334677) % self.PRIME for i in range(self.num_perm)]

    def compute_signature(self, shingles: List[str]) -> List[int]:
        if not shingles:
            return [0] * self.num_perm

        shingle_hashes = [int(hashlib.md5(s.encode('utf-8')).hexdigest()[:16], 16) for s in shingles]
        sig = []
        for i in range(self.num_perm):
            a, b = self._a[i], self._b[i]
            min_h = min(((a * h + b) % self.PRIME) for h in shingle_hashes)
            sig.append(min_h)
        return sig

    def jaccard_similarity(self, sig1: List[int], sig2: List[int]) -> float:
        if not sig1 or not sig2 or len(sig1) != len(sig2):
            return 0.0
        matches = sum(1 for h1, h2 in zip(sig1, sig2) if h1 == h2)
        return matches / float(len(sig1))


class DedupGate:
    """
    Two-tier deduplication gate with persistent SQLite storage.
    """

    def __init__(self, db_path: Path = DB_PATH, threshold: float = 0.8):
        self._db_path = db_path
        self._threshold = threshold
        self._minhash = MinHash()
        self._seen_urls: Set[str] = set()
        self._minhash_index: List[Tuple[str, List[int]]] = []  # List of (article_id, signature)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite persistent table and load existing seen URLs and MinHash index."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_articles (
                    canon_url TEXT PRIMARY KEY,
                    article_id TEXT,
                    title TEXT,
                    minhash_sig BLOB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

            # Load into memory
            cursor = conn.cursor()
            cursor.execute("SELECT canon_url, article_id, minhash_sig FROM seen_articles")
            for canon_url, article_id, sig_blob in cursor.fetchall():
                self._seen_urls.add(canon_url)
                if sig_blob:
                    sig = list(struct.unpack(f">{MinHash.NUM_PERMUTATIONS}Q", sig_blob))
                    self._minhash_index.append((article_id, sig))

        logger.info(f"DedupGate initialized: {len(self._seen_urls)} canonical URLs and {len(self._minhash_index)} titles loaded from disk.")

    def check_and_add(self, article: Article) -> bool:
        """
        Check if article is duplicate.
        Returns True if DUPLICATE (reject article).
        Returns False if NEW (article accepted & indexed).
        """
        canon_url = canonicalize_url(article.url)

        # Tier 1: Canonical URL check
        if canon_url in self._seen_urls:
            return True  # Duplicate URL

        # Tier 2: Title MinHash Jaccard check on Bloom/URL miss or soft match
        norm_title = normalize_title(article.title)
        shingles = get_shingles(norm_title)
        candidate_sig = self._minhash.compute_signature(shingles)

        for existing_id, existing_sig in self._minhash_index:
            sim = self._minhash.jaccard_similarity(candidate_sig, existing_sig)
            if sim >= self._threshold:
                logger.info(f"Duplicate title detected by MinHash (sim={sim:.2f}): '{article.title}'")
                return True  # Duplicate title

        # Article is genuinely NEW -> Add to memory & persist to SQLite
        self._seen_urls.add(canon_url)
        self._minhash_index.append((article.id, candidate_sig))

        sig_blob = struct.pack(f">{MinHash.NUM_PERMUTATIONS}Q", *candidate_sig)
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO seen_articles (canon_url, article_id, title, minhash_sig) VALUES (?, ?, ?, ?)",
                    (canon_url, article.id, article.title, sig_blob)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error persisting article to DedupGate DB: {e}")

        return False  # Accepted
