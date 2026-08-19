"""
Data Privacy Manager for GDPR/CCPA Compliance.

Provides:
- Right to be forgotten (GDPR Art. 17)
- Data portability (GDPR Art. 20)
- Data retention policies
- Consent management

Usage:
    from src.compliance import DataPrivacyManager
    
    manager = DataPrivacyManager()
    
    # Process deletion request
    report = manager.process_deletion_request(user_id="user123")
    
    # Export user data
    export = manager.export_user_data(user_id="user123")
    
    # Apply retention policy
    cleanup = manager.apply_retention_policy()
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DeletionReport:
    """Report of a data deletion request (GDPR Art. 17)."""
    user_id: str
    request_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_time: Optional[datetime] = None
    records_deleted: int = 0
    tables_affected: List[str] = field(default_factory=list)
    success: bool = False
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "request_time": self.request_time.isoformat(),
            "completed_time": self.completed_time.isoformat() if self.completed_time else None,
            "records_deleted": self.records_deleted,
            "tables_affected": self.tables_affected,
            "success": self.success,
            "errors": self.errors,
        }


@dataclass
class DataExport:
    """Export of user data (GDPR Art. 20)."""
    user_id: str
    export_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    data: Dict[str, Any] = field(default_factory=dict)
    format: str = "json"
    size_bytes: int = 0
    
    def to_json(self) -> str:
        """Export as JSON string."""
        export_data = {
            "user_id": self.user_id,
            "export_time": self.export_time.isoformat(),
            "data": self.data,
        }
        return json.dumps(export_data, indent=2, default=str)
    
    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "export_time": self.export_time.isoformat(),
            "data": self.data,
            "format": self.format,
            "size_bytes": self.size_bytes,
        }


@dataclass
class RetentionReport:
    """Report of retention policy application."""
    run_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    articles_deleted: int = 0
    queries_deleted: int = 0
    alerts_deleted: int = 0
    space_freed_bytes: int = 0
    next_run: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        return {
            "run_time": self.run_time.isoformat(),
            "articles_deleted": self.articles_deleted,
            "queries_deleted": self.queries_deleted,
            "alerts_deleted": self.alerts_deleted,
            "space_freed_bytes": self.space_freed_bytes,
            "next_run": self.next_run.isoformat() if self.next_run else None,
        }


# =============================================================================
# COMPLIANCE CONFIGURATION
# =============================================================================

@dataclass
class ComplianceConfig:
    """Configuration for compliance features."""
    # GDPR settings
    gdpr_enabled: bool = True
    data_retention_days: int = 730  # 2 years default
    auto_cleanup: bool = True
    anonymize_pii: bool = True
    
    # CCPA settings
    ccpa_enabled: bool = True
    do_not_sell: bool = False
    
    # Data classification
    public_data: List[str] = field(default_factory=lambda: [
        "article_content", "summaries", "metadata"
    ])
    sensitive_data: List[str] = field(default_factory=lambda: [
        "user_queries", "alert_preferences", "api_keys"
    ])
    encrypted_fields: List[str] = field(default_factory=lambda: [
        "api_keys", "user_credentials"
    ])
    
    @classmethod
    def from_yaml(cls, path: str) -> "ComplianceConfig":
        """Load configuration from YAML file."""
        try:
            with open(path, 'r') as f:
                data = yaml.safe_load(f)
            
            compliance = data.get("compliance", {})
            gdpr = compliance.get("gdpr", {})
            ccpa = compliance.get("ccpa", {})
            classification = compliance.get("data_classification", {})
            
            return cls(
                gdpr_enabled=gdpr.get("enabled", True),
                data_retention_days=gdpr.get("data_retention_days", 730),
                auto_cleanup=gdpr.get("auto_cleanup", True),
                anonymize_pii=gdpr.get("anonymize_pii", True),
                ccpa_enabled=ccpa.get("enabled", True),
                do_not_sell=ccpa.get("do_not_sell", False),
                public_data=classification.get("public_data", []),
                sensitive_data=classification.get("sensitive_data", []),
                encrypted_fields=classification.get("encrypted_fields", []),
            )
        except Exception as e:
            logger.warning(f"Failed to load compliance config: {e}, using defaults")
            return cls()


# =============================================================================
# DATA PRIVACY MANAGER
# =============================================================================

class DataPrivacyManager:
    """
    Manages data privacy operations for GDPR/CCPA compliance.
    
    Provides:
    - process_deletion_request(): GDPR Article 17 (Right to be forgotten)
    - export_user_data(): GDPR Article 20 (Data portability)
    - apply_retention_policy(): Automatic data cleanup
    """
    
    def __init__(self, config: ComplianceConfig = None):
        """Initialize with optional configuration."""
        self._config = config or ComplianceConfig()
        self._audit_log: List[Dict[str, Any]] = []
        logger.info("DataPrivacyManager initialized")
    
    def _get_connection(self):
        """Get or create database connection."""
        import sqlite3
        from src.storage.sqlite_engine import DEFAULT_CANONICAL_DB_PATH
        db_path = DEFAULT_CANONICAL_DB_PATH
        if not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def process_deletion_request(self, user_id: str) -> DeletionReport:
        """
        Process a data deletion request (GDPR Article 17).
        
        Deletes all data associated with the user including:
        - Search queries
        - Alert preferences
        - API keys
        - User preferences
        
        Note: Articles are public data and are not deleted.
        
        Args:
            user_id: Unique identifier for the user
        
        Returns:
            DeletionReport with details of what was deleted
        """
        report = DeletionReport(user_id=user_id)
        
        try:
            # Delete from user-related tables
            # Note: Using parameterized queries to prevent SQL injection
            tables_to_clean = [
                ("user_queries", "user_id"),
                ("user_alerts", "user_id"),
                ("api_keys", "user_id"),
                ("user_preferences", "user_id"),
                ("user_topics", "user_id"),
                ("user_watchlist", "user_id"),
                ("user_sources", "user_id"),
                ("user_bookmarks", "user_id"),
                ("user_reading_history", "user_id"),
            ]
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                for table, column in tables_to_clean:
                    try:
                        # Check if table exists
                        cursor.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                            (table,)
                        )
                        if cursor.fetchone():
                            cursor.execute(f"DELETE FROM {table} WHERE {column} = ?", (user_id,))
                            deleted = cursor.rowcount
                            if deleted > 0:
                                report.records_deleted += deleted
                                report.tables_affected.append(table)
                    except Exception as e:
                        logger.debug(f"Table {table} not found or error: {e}")
                
                conn.commit()
            
            report.success = True
            report.completed_time = datetime.now(UTC)
            
            # Audit log
            self._audit_log.append({
                "action": "deletion_request",
                "user_id": user_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "records_deleted": report.records_deleted,
            })
            
            logger.info(f"Deletion request processed for {user_id}: {report.records_deleted} records deleted")
            
        except Exception as e:
            report.errors.append(str(e))
            logger.error(f"Deletion request failed for {user_id}: {e}")
        
        return report
    
    def export_user_data(self, user_id: str) -> DataExport:
        """
        Export all data associated with a user (GDPR Article 20).
        
        Exports:
        - Search queries
        - Alert preferences
        - User preferences
        - Account metadata
        
        Args:
            user_id: Unique identifier for the user
        
        Returns:
            DataExport containing all user data in JSON format
        """
        export = DataExport(user_id=user_id)
        export.data = {
            "user_id": user_id,
            "export_date": datetime.now(UTC).isoformat(),
            "queries": [],
            "alerts": [],
            "preferences": {},
            "account": {},
        }
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Export queries
                try:
                    cursor.execute("SELECT * FROM user_queries WHERE user_id = ?", (user_id,))
                    export.data["queries"] = [dict(row) for row in cursor.fetchall()]
                except Exception as e:
                    logger.warning(f"export_user_data: suppressed {type(e).__name__}: {e}")
                    pass
                
                # Export alerts
                try:
                    cursor.execute("SELECT * FROM user_alerts WHERE user_id = ?", (user_id,))
                    export.data["alerts"] = [dict(row) for row in cursor.fetchall()]
                except Exception as e:
                    logger.warning(f"export_user_data: suppressed {type(e).__name__}: {e}")
                    pass
                
                # Export preferences
                try:
                    cursor.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,))
                    row = cursor.fetchone()
                    if row:
                        export.data["preferences"] = dict(row)
                except Exception as e:
                    logger.warning(f"export_user_data: suppressed {type(e).__name__}: {e}")
                    pass
            
            # Calculate size
            json_str = export.to_json()
            export.size_bytes = len(json_str.encode('utf-8'))
            
            # Audit log
            self._audit_log.append({
                "action": "data_export",
                "user_id": user_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "size_bytes": export.size_bytes,
            })
            
            logger.info(f"Data export generated for {user_id}: {export.size_bytes} bytes")
            
        except Exception as e:
            export.data["error"] = str(e)
            logger.error(f"Data export failed for {user_id}: {e}")
        
        return export
    
    def apply_retention_policy(self) -> RetentionReport:
        """
        Apply data retention policy to clean up old data.
        
        Deletes:
        - Articles older than retention_days
        - Old search queries
        - Expired alerts
        
        Returns:
            RetentionReport with cleanup statistics
        """
        report = RetentionReport()
        
        if not self._config.auto_cleanup:
            logger.info("Auto cleanup is disabled, skipping retention policy")
            return report
        
        cutoff_date = datetime.now(UTC) - timedelta(days=self._config.data_retention_days)
        cutoff_str = cutoff_date.isoformat()
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Delete old canonical articles and legacy articles
                try:
                    cursor.execute("DELETE FROM canonical_articles WHERE discovered_at < ?", (cutoff_str,))
                    report.articles_deleted += cursor.rowcount
                except Exception as e:
                    logger.debug(f"Canonical article cleanup error: {e}")

                try:
                    cursor.execute("""
                        DELETE FROM articles 
                        WHERE (retention_expiry IS NOT NULL AND retention_expiry < ?)
                           OR (retention_expiry IS NULL AND scraped_at < ?)
                    """, (cutoff_str, cutoff_str))
                    report.articles_deleted += cursor.rowcount
                except Exception as e:
                    logger.debug(f"Article cleanup error: {e}")
                    report.articles_deleted = cursor.rowcount
                except Exception as e:
                    logger.debug(f"Article cleanup error: {e}")
                
                # Delete old queries
                try:
                    cursor.execute(
                        "DELETE FROM user_queries WHERE created_at < ?",
                        (cutoff_str,)
                    )
                    report.queries_deleted = cursor.rowcount
                except Exception as e:
                    logger.warning(f"apply_retention_policy: suppressed {type(e).__name__}: {e}")
                    pass
                
                # Delete expired alerts
                try:
                    cursor.execute(
                        "DELETE FROM user_alerts WHERE expires_at < ?",
                        (datetime.now(UTC).isoformat(),)
                    )
                    report.alerts_deleted = cursor.rowcount
                except Exception as e:
                    logger.warning(f"apply_retention_policy: suppressed {type(e).__name__}: {e}")
                    pass
                
                conn.commit()
                
                # Vacuum to reclaim space
                cursor.execute("VACUUM")
            
            report.next_run = datetime.now(UTC) + timedelta(days=1)
            
            # Audit log
            self._audit_log.append({
                "action": "retention_cleanup",
                "timestamp": datetime.now(UTC).isoformat(),
                "articles_deleted": report.articles_deleted,
                "queries_deleted": report.queries_deleted,
                "alerts_deleted": report.alerts_deleted,
            })
            
            logger.info(
                f"Retention policy applied: {report.articles_deleted} articles, "
                f"{report.queries_deleted} queries, {report.alerts_deleted} alerts deleted"
            )
            
        except Exception as e:
            logger.error(f"Retention policy failed: {e}")
        
        return report
    
    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Get the audit log of all privacy operations."""
        return self._audit_log.copy()
    
    def classify_data(self, field_name: str) -> str:
        """
        Classify a data field as public, sensitive, or encrypted.
        
        Args:
            field_name: Name of the data field
        
        Returns:
            Classification: "public", "sensitive", or "encrypted"
        """
        if field_name in self._config.encrypted_fields:
            return "encrypted"
        elif field_name in self._config.sensitive_data:
            return "sensitive"
        elif field_name in self._config.public_data:
            return "public"
        else:
            return "unclassified"
