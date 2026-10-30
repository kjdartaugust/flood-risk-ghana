"""Supabase JWT verification and auth dependencies.

Supabase issues HS256 JWTs signed with the project's JWT secret. We verify the
signature and expiry, then expose the user as a lightweight principal. Endpoints
that require auth depend on `require_user`; optional-auth endpoints use
`get_current_user`.

The scheduled refresh isn't a user. It proves itself with a GitHub Actions OIDC
token instead — see `is_github_workflow`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JOSEError, JWTError, jwt

from app.config import settings

log = logging.getLogger("security")

bearer = HTTPBearer(auto_error=False)

# A GitHub Actions job can ask GitHub for a short-lived JWT that names the repo
# and workflow it is running, signed with keys GitHub publishes. Checking that
# signature proves a request comes from our own workflow — with no shared secret
# for anyone to generate, copy between GitHub and the host, or leak.
GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
# The audience `refresh.yml` asks for. A token this repo minted for anything
# else (a cloud login from another workflow, say) is refused here.
CRON_AUDIENCE = "floodwatch-refresh"

_github_jwks_cache: dict = {"keys": [], "fetched": 0.0}


async def _github_jwks() -> dict:
    """GitHub's public signing keys, refetched hourly to follow key rotation."""
    cache = _github_jwks_cache
    if not cache["keys"] or time.monotonic() - cache["fetched"] > 3600:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{GITHUB_OIDC_ISSUER}/.well-known/jwks")
            r.raise_for_status()
        cache.update(keys=r.json()["keys"], fetched=time.monotonic())
    return {"keys": cache["keys"]}


async def is_github_workflow(token: str, repo: str, workflow: str) -> bool:
    """True if `token` is a live GitHub Actions OIDC token from `workflow` in `repo`."""
    try:
        keys = await _github_jwks()
    except (httpx.HTTPError, KeyError, ValueError):
        log.warning("could not fetch GitHub's OIDC signing keys", exc_info=True)
        return False
    try:
        # Pinning RS256 matters: a token that names HS256 must not get to use a
        # public key as its HMAC secret.
        claims = jwt.decode(token, keys, algorithms=["RS256"],
                            audience=CRON_AUDIENCE, issuer=GITHUB_OIDC_ISSUER)
    except JOSEError:
        return False
    # "<owner>/<repo>/.github/workflows/<file>@<ref>" — it names the repo too, so
    # a fork's copy of the workflow doesn't pass. GitHub names are
    # case-insensitive, and the host may not spell the repo as GitHub does.
    prefix = f"{repo}/.github/workflows/{workflow}@".lower()
    return str(claims.get("workflow_ref", "")).lower().startswith(prefix)


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
