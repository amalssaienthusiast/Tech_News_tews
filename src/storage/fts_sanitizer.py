"""
FTS5 Query Sanitizer and Match Expression Builder.
Location: src/storage/fts_sanitizer.py

Sanitizes raw user inputs, neutralizing SQLite FTS5 syntax errors, operators,
and injection patterns while supporting phrase search and prefix matching.
"""

from __future__ import annotations

import re
from typing import List, Optional

# Regex to extract quoted phrases or individual whitespace-delimited tokens
_PHRASE_OR_WORD_PATTERN = re.compile(r'"([^"]*)"|(\S+)')

# Characters that have special meaning in FTS5 and should be stripped or escaped
_DISALLOWED_FTS_CHARS = re.compile(r'[\*\^\:\(\)\{\}\[\]\~\+\-\<\>\=]')


def sanitize_fts5_query(raw_query: str, enable_prefix: bool = True) -> Optional[str]:
    """
    Sanitize raw search string into a valid, safe SQLite FTS5 MATCH expression.

    Guarantees:
    - Never raises FTS5 syntax errors
    - Strips dangerous operators and injection characters
    - Preserves exact quoted phrases: "quantum computing" -> "quantum computing"
    - Supports prefix matching for keywords: rust async -> "rust"* "async"*
    - Returns None if sanitized query is empty
    """
    if not raw_query or not isinstance(raw_query, str):
        return None

    # Replace disallowed punctuation/operators with spaces, preserving valid quotes and text
    pre_cleaned = _DISALLOWED_FTS_CHARS.sub(" ", raw_query).strip()
    if not pre_cleaned:
        return None

    matches = _PHRASE_OR_WORD_PATTERN.findall(pre_cleaned)
    fts_tokens: List[str] = []

    for phrase, word in matches:
        if phrase:
            clean_phrase = " ".join(phrase.split()).strip()
            if clean_phrase:
                escaped = clean_phrase.replace('"', '""')
                fts_tokens.append(f'"{escaped}"')
        elif word:
            clean_word = word.strip()
            if not clean_word:
                continue

            escaped_word = clean_word.replace('"', '""')
            if enable_prefix:
                fts_tokens.append(f'"{escaped_word}"*')
            else:
                fts_tokens.append(f'"{escaped_word}"')

    if not fts_tokens:
        return None

    # FTS5 default behavior with multiple space-separated tokens is implicit AND
    return " ".join(fts_tokens)
