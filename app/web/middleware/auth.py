"""
V1 Auth middleware — single shared bearer token.
# V1 PLACEHOLDER: Replace with Discord OAuth2 + RBAC in Phase 2.
# NEVER use this in production without rotating the token and restricting access.
"""
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

bearer_scheme = HTTPBearer(auto_error=False)


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> str:
    """
    FastAPI dependency — validates the admin bearer token.
    V1 PLACEHOLDER: Replace with Discord OAuth2 RBAC in Phase 2.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != settings.admin_dashboard_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired token",
        )
    return credentials.credentials


def optional_admin(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> str | None:
    """Optional admin auth — returns None if not authenticated."""
    if not credentials:
        return None
    if credentials.credentials != settings.admin_dashboard_token:
        return None
    return credentials.credentials
