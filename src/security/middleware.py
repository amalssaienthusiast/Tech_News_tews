"""
Security Middleware, Headers Injection & FastAPI Authorization Dependencies.
Location: src/security/middleware.py
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional, Set

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .auth_manager import AuthManagerProtocol, EnvAuthManager
from .models import ApiKeyMetadata, Principal, Role
from .rate_limiter import LocalTokenBucketLimiter, RateLimiterProtocol

logger = logging.getLogger(__name__)

# Security Header Defaults
DEFAULT_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'; "
    "object-src 'none';"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware injecting modern OWASP-compliant security headers into all responses.
    """

    def __init__(
        self,
        app,
        csp_header: str = DEFAULT_CSP,
        enable_hsts: bool = True,
    ) -> None:
        super().__init__(app)
        self.csp_header = csp_header
        self.enable_hsts = enable_hsts

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = self.csp_header

        if self.enable_hsts:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware enforcing maximum request body size (default: 2 MB) to defend against DoS.
    """

    def __init__(self, app, max_body_bytes: int = 2 * 1024 * 1024) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > self.max_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body exceeds maximum size of {self.max_body_bytes} bytes"},
                    )
            except ValueError:
                pass

        return await call_next(request)


# =============================================================================
# GLOBAL SECURITY SINGLETONS & FASTAPI DEPENDENCY INJECTION
# =============================================================================

_shared_auth_manager: Optional[AuthManagerProtocol] = None
_shared_rate_limiter: Optional[RateLimiterProtocol] = None

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_manager() -> AuthManagerProtocol:
    """Get the active AuthManagerProtocol dependency."""
    global _shared_auth_manager
    if _shared_auth_manager is None:
        _shared_auth_manager = EnvAuthManager()
    return _shared_auth_manager


def set_auth_manager(manager: Optional[AuthManagerProtocol]) -> None:
    """Inject custom AuthManagerProtocol instance."""
    global _shared_auth_manager
    _shared_auth_manager = manager


def get_rate_limiter() -> RateLimiterProtocol:
    """Get the active RateLimiterProtocol dependency."""
    global _shared_rate_limiter
    if _shared_rate_limiter is None:
        _shared_rate_limiter = LocalTokenBucketLimiter()
    return _shared_rate_limiter


def set_rate_limiter(limiter: Optional[RateLimiterProtocol]) -> None:
    """Inject custom RateLimiterProtocol instance."""
    global _shared_rate_limiter
    _shared_rate_limiter = limiter


async def get_current_principal(
    request: Request,
    bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    auth_mgr: AuthManagerProtocol = Depends(get_auth_manager),
    limiter: RateLimiterProtocol = Depends(get_rate_limiter),
) -> Principal:
    """
    FastAPI dependency extracting credentials, authenticating principal,
    and enforcing token bucket rate limiting.
    """
    raw_key: Optional[str] = None

    # 1. Try Authorization: Bearer <key>
    if bearer and bearer.credentials:
        raw_key = bearer.credentials
    # 2. Try X-API-Key header fallback
    elif "x-api-key" in request.headers:
        raw_key = request.headers.get("x-api-key")

    principal: Optional[Principal] = None
    if raw_key:
        principal = auth_mgr.authenticate_key(raw_key)

    # Fallback to anonymous if unauthenticated
    if principal is None:
        principal = Principal.anonymous()

    # Rate limiting key: API Key fingerprint if authenticated, else client IP
    client_ip = request.client.host if request.client else "127.0.0.1"
    rate_key = principal.api_key_fingerprint or f"ip_{client_ip}"

    rl_result = await limiter.check_rate_limit(key=rate_key, role=principal.role)

    # Attach rate limit headers to request state
    request.state.rate_limit_result = rl_result

    if not rl_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please retry later.",
            headers={"Retry-After": str(rl_result.retry_after or 1)},
        )

    return principal


def require_role(min_role: Role):
    """Factory creating an authorization dependency for hierarchical roles."""
    async def _role_guard(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.is_authenticated and min_role != Role.ANONYMOUS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        if not principal.role.satisfies(min_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Requires '{min_role.value}' role.",
            )
        return principal
    return _role_guard


def require_scope(required_scope: str):
    """Factory creating an authorization dependency for granular permission scopes."""
    async def _scope_guard(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.is_authenticated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        if not principal.has_scope(required_scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission scope '{required_scope}'.",
            )
        return principal
    return _scope_guard
