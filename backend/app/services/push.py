"""Web Push (VAPID) delivery — the real notifier behind route alerts.

Free and vendor-neutral, which is why it's the channel here: the *browser* mints
its own push endpoint (FCM for Chrome, Mozilla autopush for Firefox) and we sign
each delivery with a VAPID keypair we own. No Firebase project, no paid SMS
gateway, nothing to bill. It also reaches Android Chrome, which is what an Accra
trotro commuter is actually carrying.

**Delivery fails open, on purpose.** Pushing is a side effect of
`evaluate_and_raise_alerts`, whose real job is to materialise the alert row —
which the map and `GET /alerts` serve regardless. A dead endpoint, a missing
VAPID key or an uninstalled `pywebpush` must never take down the ETL cycle, so
failures here are logged and reported, never raised.

Generate a keypair (once, then set the env vars it prints):

    python -m app.services.push --generate-keys
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from app.config import settings

log = logging.getLogger("push")

# pywebpush pulls in `requests`; import lazily so the app still boots — with push
# disabled rather than crashed — anywhere it isn't installed.
try:  # pragma: no cover - import guard
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover
    webpush = None  # type: ignore[assignment]
    WebPushException = Exception  # type: ignore[misc,assignment]

# Statuses that mean "this endpoint is dead": 404 never existed, 410 the user
# revoked it or the browser rotated it. Either way, stop writing to it.
GONE = (404, 410)

# Sentinel for "we couldn't even try" — distinct from a real HTTP failure.
DISABLED = 0


def push_enabled() -> bool:
    """True if we can actually deliver: keys configured *and* library present."""
    return bool(webpush is not None and settings.vapid_private_key
                and settings.vapid_public_key)


def is_gone(status: int | None) -> bool:
    """Should this subscription be deleted rather than retried?"""
    return status in GONE


def _send(sub: dict[str, Any], payload: dict[str, Any]) -> int | None:
    """Blocking send. Returns None on success, else the failing HTTP status."""
    try:
        webpush(
            subscription_info=sub,
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=settings.push_ttl_seconds,
        )
        return None
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None) or DISABLED
        if not is_gone(status):
            log.warning("web push failed (status=%s): %s", status, exc)
        return status


async def send_push(sub: dict[str, Any], payload: dict[str, Any]) -> int | None:
    """Deliver one push. None = delivered; otherwise the failing status.

    Check the result with `is_gone()` before deleting a subscription: a 503 from
    a push service is transient and must not cost the user their subscription.
    """
    if not push_enabled():
        log.info("push disabled (no VAPID keys) — would have sent %s", payload)
        return DISABLED
    # pywebpush is synchronous (requests), so keep it off the event loop.
    return await asyncio.to_thread(_send, sub, payload)


def _b64(raw: bytes) -> str:
    """base64url, unpadded — the encoding the Web Push spec uses for keys."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate_keys() -> tuple[str, str]:
    """Mint a VAPID P-256 keypair as (public, private), base64url-encoded."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    return _b64(public), _b64(private)


if __name__ == "__main__":  # pragma: no cover
    pub, priv = generate_keys()
    print("# Backend (Render → Environment):")
    print(f"VAPID_PUBLIC_KEY={pub}")
    print(f"VAPID_PRIVATE_KEY={priv}")
    print("VAPID_SUBJECT=mailto:you@example.com")
    print()
    print("# Frontend (Vercel → Environment Variables):")
    print(f"NEXT_PUBLIC_VAPID_PUBLIC_KEY={pub}")
