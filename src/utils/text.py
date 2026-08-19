"""
Text processing and sanitization utilities.
"""

import re


def sanitize_title(title: str) -> str:
    """
    Sanitizes headline titles by stripping leading numbering or rank prefixes.

    Examples:
        '1. Headline Title'        -> 'Headline Title'
        '15: Major Tech News'       -> 'Major Tech News'
        '3) New Release'           -> 'New Release'
        '1Headline'                -> 'Headline'
        '3D Printing in 2026'      -> '3D Printing in 2026' (Unchanged)
        '5G Networks'              -> '5G Networks' (Unchanged)
    """
    if not title:
        return ""
    title = title.strip()
    # Strip list numbering with separators like '1. ', '1: ', '1) ', '1 - '
    title = re.sub(r'^\d{1,3}[\.\:\)\s\-]+\s*(?=[A-Za-z])', '', title)
    # Strip glued digits from headline start (e.g., '1Apple' -> 'Apple', keeping 3D, 5G, 4K, 2FA)
    title = re.sub(r'^\d{1,2}(?=[A-Z][a-z]{2,})', '', title)
    return title.strip()
