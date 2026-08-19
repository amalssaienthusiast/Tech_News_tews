"""
Data Anonymization Pipeline for PII Detection and Redaction.

Provides:
- Email address detection and redaction
- Phone number detection and redaction
- IP address detection and redaction
- Credit card detection (Luhn validation)
- Extensible pipeline for custom redactors

Usage:
    from src.compliance import AnonymizationPipeline
    
    pipeline = AnonymizationPipeline()
    
    # Anonymize content
    clean_text, detected = pipeline.anonymize(article_content)
    
    # Check for PII
    has_pii = pipeline.has_pii(content)
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Pattern, Set, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# BASE REDACTOR
# =============================================================================

class BaseRedactor(ABC):
    """Base class for PII redactors."""
    
    name: str = "base"
    replacement: str = "[REDACTED]"
    
    @abstractmethod
    def detect(self, text: str) -> List[str]:
        """Detect PII matches in text."""
        pass
    
    @abstractmethod
    def redact(self, text: str) -> str:
        """Redact PII from text."""
        pass
    
    def has_pii(self, text: str) -> bool:
        """Check if text contains PII."""
        return len(self.detect(text)) > 0


# =============================================================================
# EMAIL REDACTOR
# =============================================================================

class EmailRedactor(BaseRedactor):
    """Detects and redacts email addresses."""
    
    name = "email"
    replacement = "[EMAIL_REDACTED]"
    
    # RFC 5322 compliant email regex (simplified)
    EMAIL_PATTERN: Pattern = re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        re.IGNORECASE
    )
    
    def detect(self, text: str) -> List[str]:
        """Detect email addresses in text."""
        return self.EMAIL_PATTERN.findall(text)
    
    def redact(self, text: str) -> str:
        """Replace email addresses with redaction marker."""
        return self.EMAIL_PATTERN.sub(self.replacement, text)


# =============================================================================
# PHONE NUMBER REDACTOR
# =============================================================================

class PhoneNumberRedactor(BaseRedactor):
    """Detects and redacts phone numbers."""
    
    name = "phone"
    replacement = "[PHONE_REDACTED]"
    
    # Common phone number patterns (US, UK, international)
    PHONE_PATTERNS: List[Pattern] = [
        # US: (123) 456-7890, 123-456-7890, 123.456.7890
        re.compile(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'),
        # International: +1 123 456 7890
        re.compile(r'\+\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}'),
        # UK: 07XXX XXXXXX
        re.compile(r'\b07\d{3}[-.\s]?\d{6}\b'),
    ]
    
    def detect(self, text: str) -> List[str]:
        """Detect phone numbers in text."""
        matches = []
        for pattern in self.PHONE_PATTERNS:
            matches.extend(pattern.findall(text))
        return matches
    
    def redact(self, text: str) -> str:
        """Replace phone numbers with redaction marker."""
        result = text
        for pattern in self.PHONE_PATTERNS:
            result = pattern.sub(self.replacement, result)
        return result


# =============================================================================
# IP ADDRESS REDACTOR
# =============================================================================

class IPAddressRedactor(BaseRedactor):
    """Detects and redacts IP addresses (IPv4 and IPv6)."""
    
    name = "ip_address"
    replacement = "[IP_REDACTED]"
    
    # IPv4 pattern
    IPV4_PATTERN: Pattern = re.compile(
        r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
        r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
    )
    
    # IPv6 pattern (simplified)
    IPV6_PATTERN: Pattern = re.compile(
        r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b|'
        r'\b(?:[0-9a-fA-F]{1,4}:){1,7}:\b|'
        r'\b(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b',
        re.IGNORECASE
    )
    
    def detect(self, text: str) -> List[str]:
        """Detect IP addresses in text."""
        matches = []
        matches.extend(self.IPV4_PATTERN.findall(text))
        matches.extend(self.IPV6_PATTERN.findall(text))
        return matches
    
    def redact(self, text: str) -> str:
        """Replace IP addresses with redaction marker."""
        result = self.IPV4_PATTERN.sub(self.replacement, text)
        result = self.IPV6_PATTERN.sub(self.replacement, result)
        return result


# =============================================================================
# CREDIT CARD DETECTOR
# =============================================================================

class CreditCardDetector(BaseRedactor):
    """Detects and redacts credit card numbers using Luhn validation."""
    
    name = "credit_card"
    replacement = "[CC_REDACTED]"
    
    # Pattern for potential card numbers (13-19 digits with optional separators)
    CARD_PATTERN: Pattern = re.compile(
        r'\b(?:\d{4}[-\s]?){3,4}\d{1,4}\b'
    )
    
    @staticmethod
    def luhn_check(card_number: str) -> bool:
        """Validate card number using Luhn algorithm."""
        digits = [int(d) for d in card_number if d.isdigit()]
        if len(digits) < 13 or len(digits) > 19:
            return False
        
        checksum = 0
        for i, digit in enumerate(reversed(digits)):
            if i % 2 == 1:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        
        return checksum % 10 == 0
    
    def detect(self, text: str) -> List[str]:
        """Detect credit card numbers using pattern + Luhn validation."""
        matches = []
        for match in self.CARD_PATTERN.finditer(text):
            card = match.group()
            if self.luhn_check(card):
                matches.append(card)
        return matches
    
    def redact(self, text: str) -> str:
        """Replace valid credit card numbers with redaction marker."""
        result = text
        for match in self.CARD_PATTERN.finditer(text):
            card = match.group()
            if self.luhn_check(card):
                result = result.replace(card, self.replacement)
        return result


# =============================================================================
# SSN DETECTOR (US)
# =============================================================================

class SSNRedactor(BaseRedactor):
    """Detects and redacts US Social Security Numbers."""
    
    name = "ssn"
    replacement = "[SSN_REDACTED]"
    
    # SSN pattern: XXX-XX-XXXX
    SSN_PATTERN: Pattern = re.compile(
        r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b'
    )
    
    def detect(self, text: str) -> List[str]:
        """Detect SSN patterns in text."""
        return self.SSN_PATTERN.findall(text)
    
    def redact(self, text: str) -> str:
        """Replace SSN patterns with redaction marker."""
        return self.SSN_PATTERN.sub(self.replacement, text)


# =============================================================================
# ANONYMIZATION PIPELINE
# =============================================================================

@dataclass
class AnonymizationResult:
    """Result of anonymization operation."""
    original_length: int
    anonymized_length: int
    pii_types_found: List[str]
    redaction_count: int
    
    def to_dict(self) -> dict:
        return {
            "original_length": self.original_length,
            "anonymized_length": self.anonymized_length,
            "pii_types_found": self.pii_types_found,
            "redaction_count": self.redaction_count,
        }


class AnonymizationPipeline:
    """
    Pipeline for detecting and redacting PII from text.
    
    Combines multiple redactors to comprehensively anonymize content.
    """
    
    def __init__(self, redactors: List[BaseRedactor] = None):
        """
        Initialize pipeline with redactors.
        
        Args:
            redactors: List of redactors to use. Defaults to standard set.
        """
        if redactors is None:
            redactors = [
                EmailRedactor(),
                PhoneNumberRedactor(),
                IPAddressRedactor(),
                CreditCardDetector(),
                SSNRedactor(),
            ]
        
        self._redactors = redactors
        logger.info(f"AnonymizationPipeline initialized with {len(redactors)} redactors")
    
    def anonymize(self, text: str) -> Tuple[str, AnonymizationResult]:
        """
        Anonymize text by redacting all detected PII.
        
        Args:
            text: Text to anonymize
        
        Returns:
            Tuple of (anonymized_text, AnonymizationResult)
        """
        if not text:
            return text, AnonymizationResult(0, 0, [], 0)
        
        original_length = len(text)
        pii_types = []
        redaction_count = 0
        result = text
        
        for redactor in self._redactors:
            detections = redactor.detect(result)
            if detections:
                pii_types.append(redactor.name)
                redaction_count += len(detections)
                result = redactor.redact(result)
        
        return result, AnonymizationResult(
            original_length=original_length,
            anonymized_length=len(result),
            pii_types_found=pii_types,
            redaction_count=redaction_count,
        )
    
    def has_pii(self, text: str) -> bool:
        """Check if text contains any PII."""
        for redactor in self._redactors:
            if redactor.has_pii(text):
                return True
        return False
    
    def detect_all(self, text: str) -> dict:
        """
        Detect all PII in text without redacting.
        
        Returns:
            Dict mapping PII type to list of matches
        """
        results = {}
        for redactor in self._redactors:
            detections = redactor.detect(text)
            if detections:
                results[redactor.name] = detections
        return results
    
    def add_redactor(self, redactor: BaseRedactor):
        """Add a custom redactor to the pipeline."""
        self._redactors.append(redactor)
        logger.info(f"Added redactor: {redactor.name}")
    
    @property
    def redactors(self) -> List[str]:
        """Get list of redactor names."""
        return [r.name for r in self._redactors]
