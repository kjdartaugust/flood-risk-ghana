"""Supabase JWT verification and auth dependencies.

Supabase issues HS256 JWTs signed with the project's JWT secret. We verify the
signature and expiry, then expose the user as a lightweight principal. Endpoints
that require auth depend on `require_user`; optional-auth endpoints use
`get_current_user`.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    id: str
    email: str | None
    role: str


def _decode(token: str) -> dict:
    if not settings.supabase_jwt_secret:
        # Dev fallback: accept unverified tokens only outside production.
        if settings.is_prod:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                                "Auth not configured")
        return jwt.get_unverified_claims(token)
    return jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
        options={"verify_aud": False},
    )


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal | None:
    """Return the principal if a valid token is present, else None."""
    if creds is None:
        return None
    try:
        claims = _decode(creds.credentials)
    except JWTError:
        return None
    sub = claims.get("sub")
    if not sub:
        return None
    return Principal(
        id=sub,
        email=claims.get("email"),
        role=claims.get("role", "authenticated"),
    )


async def require_user(
    user: Principal | None = Depends(get_current_user),
) -> Principal:
    """Require a valid authenticated user, else 401."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
