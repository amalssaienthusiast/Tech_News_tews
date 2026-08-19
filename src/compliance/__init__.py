"""
Compliance Module for Tech News Scraper.

Provides GDPR/CCPA compliance features:
- Data privacy management (deletion, export, retention)
- PII detection and anonymization
- Compliance configuration and reporting
"""

from .data_privacy_manager import DataPrivacyManager, DeletionReport, DataExport
from .data_anonymization import (
    AnonymizationPipeline,
    EmailRedactor,
    PhoneNumberRedactor,
    IPAddressRedactor,
)

__all__ = [
    "DataPrivacyManager",
    "DeletionReport",
    "DataExport",
    "AnonymizationPipeline",
    "EmailRedactor",
    "PhoneNumberRedactor",
    "IPAddressRedactor",
]
