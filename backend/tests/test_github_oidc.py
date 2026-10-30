"""GitHub Actions OIDC: the refresh cron's only credential, so check it hard.

Real RS256 tokens, signed with a throwaway key standing in for GitHub's. Only
the key fetch is faked, so signature, expiry, audience and issuer checks are the
real ones.
"""
from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

from app import security

REPO = "owner/repo"


def _keypair() -> tuple[bytes, dict]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return private_pem, {**jwk.construct(public_pem, "RS256").to_dict(), "kid": "k1"}


GITHUB_KEY, GITHUB_JWK = _keypair()
SOMEONE_ELSES_KEY, _ = _keypair()


def _token(key: bytes | str = GITHUB_KEY, alg: str = "RS256", **claims) -> str:
    now = int(time.time())
    return jwt.encode({
        "iss": security.GITHUB_OIDC_ISSUER,
        "aud": security.CRON_AUDIENCE,
        "repository": REPO,
        "workflow_ref": f"{REPO}/.github/workflows/refresh.yml@refs/heads/main",
        "iat": now, "nbf": now - 60, "exp": now + 300,
        **claims,
    }, key, algorithm=alg, headers={"kid": "k1"})


@pytest.fixture(autouse=True)
def github_publishes_our_test_key(monkeypatch):
    async def jwks():
        return {"keys": [GITHUB_JWK]}

    monkeypatch.setattr(security, "_github_jwks", jwks)


async def _passes(token: str, repo: str = REPO) -> bool:
    return await security.is_github_workflow(token, repo, "refresh.yml")


@pytest.mark.asyncio
async def test_accepts_the_repos_refresh_workflow():
    assert await _passes(_token())
    # GitHub names are case-insensitive; the host may spell the repo differently.
    assert await _passes(_token(), repo="Owner/Repo")


@pytest.mark.asyncio
@pytest.mark.parametrize("claims", [
    # a fork running its copy of the workflow
    {"workflow_ref": "fork/repo/.github/workflows/refresh.yml@refs/heads/main"},
    # another workflow in the same repo
    {"workflow_ref": f"{REPO}/.github/workflows/ci.yml@refs/heads/main"},
    # minted for some other service
    {"aud": "sts.amazonaws.com"},
    {"iss": "https://token.actions.example.com"},
    {"exp": int(time.time()) - 1},
])
async def test_rejects_tokens_not_from_the_refresh_workflow(claims):
    assert not await _passes(_token(**claims))


@pytest.mark.asyncio
async def test_rejects_tokens_github_did_not_sign():
    assert not await _passes(_token(key=SOMEONE_ELSES_KEY))
    assert not await _passes(_token(key="guessable", alg="HS256"))
    assert not await _passes("not-a-jwt")


@pytest.mark.asyncio
async def test_fails_closed_when_github_keys_are_unreachable(monkeypatch):
    async def down():
        raise security.httpx.ConnectError("no route to host")

    monkeypatch.setattr(security, "_github_jwks", down)
    assert not await _passes(_token())
