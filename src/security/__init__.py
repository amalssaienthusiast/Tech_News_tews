"""
Security and SSRF Protection Package for Tech News Scrapper.
Location: src/security/__init__.py
"""

from .auth_manager import AuthManagerProtocol, EnvAuthManager
from .middleware import (
    DEFAULT_CSP,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    get_auth_manager,
    get_current_principal,
    get_rate_limiter,
    require_role,
    require_scope,
    set_auth_manager,
    set_rate_limiter,
)
from .models import (
    ApiKeyMetadata,
    Principal,
    RateLimitResult,
    Role,
    STANDARD_SCOPES,
    hash_key_fingerprint,
)
from .rate_limiter import (
    DEFAULT_ROLE_QUOTAS,
    LocalTokenBucketLimiter,
    RateLimiterProtocol,
)
from .ssrf_guard import (
    PayloadSizeLimitExceeded,
    SSRFConfig,
    SSRFGuard,
    SSRFSecurityError,
    SafeHttpClient,
)
from .acquisition_policy import (
    SafeAcquisitionClient,
    SafeRobotsPolicyEngine,
    can_fetch_robots,
    get_acquisition_ssrf_guard,
    get_robots_policy_engine,
    get_safe_http_client,
    is_safe_acquisition_target,
    set_acquisition_ssrf_guard,
    set_safe_http_client,
    validate_acquisition_url,
)

__all__ = [
    # Acquisition Policy & SSRF
    "SSRFConfig",
    "SSRFGuard",
    "SSRFSecurityError",
    "PayloadSizeLimitExceeded",
    "SafeHttpClient",
    "SafeAcquisitionClient",
    "SafeRobotsPolicyEngine",
    "validate_acquisition_url",
    "is_safe_acquisition_target",
    "can_fetch_robots",
    "get_acquisition_ssrf_guard",
    "set_acquisition_ssrf_guard",
    "get_safe_http_client",
    "set_safe_http_client",
    "get_robots_policy_engine",
    # Models & RBAC
    "Role",
    "Principal",
    "ApiKeyMetadata",
    "RateLimitResult",
    "STANDARD_SCOPES",
    "hash_key_fingerprint",
    # Rate Limiting
    "RateLimiterProtocol",
    "LocalTokenBucketLimiter",
    "DEFAULT_ROLE_QUOTAS",
    # Auth
    "AuthManagerProtocol",
    "EnvAuthManager",
    "get_auth_manager",
    "set_auth_manager",
    "get_rate_limiter",
    "set_rate_limiter",
    "get_current_principal",
    "require_role",
    "require_scope",
    # Middleware
    "SecurityHeadersMiddleware",
    "RequestSizeLimitMiddleware",
    "DEFAULT_CSP",
]