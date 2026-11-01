"""Web Push delivery: the notifier must be safe to fail and honest about it.

No DB and no network: `_notify` is exercised against a stub session, because
what's being tested is the *dispatch* decision (push? prune? log?), not storage.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import settings
from app.main import create_app
from app.models import AlertSubscription, RouteAlert
from app.schemas import SubscribeRequest
from app.services import alerts_service, push

# Shaped like a browser's: a real P-256 point and a 16-byte auth secret.
SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc",
       "keys": {"p256dh": push.generate_keys()[0], "auth": "AAAAAAAAAAAAAAAAAAAAAA"}}


class FakeDB:
    """Just enough AsyncSession for `_notify`."""

    def __init__(self) -> None:
        self.deleted: list[object] = []

    async def delete(self, obj: object) -> None:
        self.deleted.append(obj)


@pytest.fixture
def alert():
    return RouteAlert(route_id="r1", level="severe",
                      message="Kaneshie–Circle: heavy rain expected",
                      expected_precip_mm=42.0, risk_score=81.0)


def _sub(channel="push", handle=SUB):
    return AlertSubscription(id="s1", user_id="u1", route_id="r1",
                             channel=channel, push_subscription=handle)


def test_push_is_disabled_without_keys():
    """The default posture. Nothing configured ⇒ nothing promised."""
    assert push.push_enabled() is False


def test_gone_means_prune_but_transient_failure_does_not():
    """A 503 from a push service must not cost a user their subscription."""
    assert push.is_gone(410) is True   # revoked / rotated
    assert push.is_gone(404) is True   # never existed
    assert push.is_gone(503) is False  # push service having a bad day
    assert push.is_gone(None) is False  # delivered


@pytest.mark.asyncio
async def test_send_push_is_a_no_op_when_unconfigured():
    """It must return, not raise — the ETL cycle runs through this."""
    assert await push.send_push(SUB, {"title": "x"}) == push.DISABLED


@pytest.mark.asyncio
async def test_notify_pushes_to_push_subscribers(monkeypatch, alert):
    sent = []

    async def fake_send(handle, payload):
        sent.append((handle, payload))
        return None  # delivered

    monkeypatch.setattr(alerts_service, "send_push", fake_send)
    db = FakeDB()
    await alerts_service._notify(db, _sub(), alert)

    assert len(sent) == 1
    handle, payload = sent[0]
    assert handle == SUB
    assert payload["level"] == "severe"
    assert alert.message in payload["body"]
    assert db.deleted == []


@pytest.mark.asyncio
async def test_notify_prunes_a_dead_endpoint(monkeypatch, alert):
    """410 Gone: keep it and we push into the void every cycle, forever."""
    async def gone(handle, payload):
        return 410

    monkeypatch.setattr(alerts_service, "send_push", gone)
    db = FakeDB()
    sub = _sub()
    await alerts_service._notify(db, sub, alert)
    assert db.deleted == [sub]


@pytest.mark.asyncio
async def test_notify_keeps_a_subscription_after_a_transient_failure(
    monkeypatch, alert
):
    async def flaky(handle, payload):
        return 503

    monkeypatch.setattr(alerts_service, "send_push", flaky)
    db = FakeDB()
    await alerts_service._notify(db, _sub(), alert)
    assert db.deleted == []


@pytest.mark.asyncio
async def test_notify_does_not_push_to_web_only_subscribers(monkeypatch, alert):
    """channel='web' is in-app only; the alert is already on GET /alerts."""
    async def boom(handle, payload):
        raise AssertionError("must not push to a web-channel subscriber")

    monkeypatch.setattr(alerts_service, "send_push", boom)
    await alerts_service._notify(FakeDB(), _sub(channel="web", handle=None), alert)


def test_push_channel_requires_a_handle():
    """Storing channel='push' with nothing to push to is a silent dead end."""
    with pytest.raises(ValidationError):
        SubscribeRequest(route_id="r1", channel="push")
    ok = SubscribeRequest(route_id="r1", channel="push", push_subscription=SUB)
    assert ok.push_subscription.endpoint == SUB["endpoint"]


def test_push_subscription_needs_its_encryption_keys():
    with pytest.raises(ValidationError, match="auth"):
        SubscribeRequest(route_id="r1", channel="push",
                         push_subscription={"endpoint": "https://x",
                                            "keys": {"p256dh": "B..."}})


def test_push_keys_must_be_a_browsers():
    """Anyone can subscribe, so keys we couldn't encrypt to are refused up front."""
    for keys in ({"p256dh": "BPk...", "auth": SUB["keys"]["auth"]},
                 {"p256dh": SUB["keys"]["p256dh"], "auth": "k9..."}):
        with pytest.raises(ValidationError, match="push key"):
            SubscribeRequest(route_id="r1", channel="push",
                             push_subscription={**SUB, "keys": keys})


@pytest.mark.asyncio
async def test_a_broken_subscription_cannot_stop_an_alert_run(monkeypatch):
    """Junk keys raise binascii.Error, not WebPushException, and an unreachable
    push service raises a requests error. Both must come back as a failed send,
    never as an exception in the middle of evaluate_and_raise_alerts."""
    pub, priv = push.generate_keys()
    monkeypatch.setattr(settings, "vapid_public_key", pub)
    monkeypatch.setattr(settings, "vapid_private_key", priv)
    junk = {**SUB, "keys": {"p256dh": "check", "auth": "check"}}
    assert await push.send_push(junk, {"title": "x"}) == push.DISABLED

    def unreachable(**kwargs):
        raise ConnectionError("no route to fcm.googleapis.com")

    monkeypatch.setattr(push, "webpush", unreachable)
    assert await push.send_push(SUB, {"title": "x"}) == push.DISABLED


def test_push_endpoint_must_be_a_browser_push_service():
    """We POST to this URL on every alert, so a caller must not get to pick it."""
    for bad in ("https://169.254.169.254/latest/meta-data",
                "http://fcm.googleapis.com/fcm/send/abc",
                "https://fcm.googleapis.com.evil.example/abc",
                "https://fcm.googleapis.com@evil.example/abc",
                "https://evilpush.apple.com/abc"):
        with pytest.raises(ValidationError, match="push service"):
            SubscribeRequest(route_id="r1", channel="push",
                             push_subscription={**SUB, "endpoint": bad})
    for good in ("https://updates.push.services.mozilla.com/wpush/v2/abc",
                 "https://web.push.apple.com/QK9abc",
                 "https://wns2-par02p.notify.windows.com/w/?token=abc"):
        SubscribeRequest(route_id="r1", channel="push",
                         push_subscription={**SUB, "endpoint": good})


def test_generated_vapid_keys_are_the_right_shape():
    """P-256: a 65-byte uncompressed point and a 32-byte scalar, base64url."""
    pub, priv = push.generate_keys()
    assert len(pub) == 87 and len(priv) == 43
    assert "=" not in pub and "+" not in pub and "/" not in pub


def _db_down():
    raise ConnectionError("database unreachable")


@pytest.mark.asyncio
async def test_keys_from_the_environment_win(monkeypatch):
    """Bring-your-own keys are used as-is; the database isn't even opened."""
    monkeypatch.setattr(settings, "vapid_public_key", "pub")
    monkeypatch.setattr(settings, "vapid_private_key", "priv")
    monkeypatch.setattr(push, "SessionLocal", _db_down)
    await push.load_keys()
    assert (settings.vapid_public_key, settings.vapid_private_key) == ("pub", "priv")


@pytest.mark.asyncio
async def test_loading_keys_survives_a_database_outage(monkeypatch):
    """It runs at boot: no keys must mean no push, not no app."""
    monkeypatch.setattr(settings, "vapid_public_key", "")
    monkeypatch.setattr(settings, "vapid_private_key", "")
    monkeypatch.setattr(push, "SessionLocal", _db_down)
    await push.load_keys()
    assert push.push_enabled() is False


def test_vapid_key_endpoint_503s_when_push_is_off(monkeypatch):
    """The UI reads this to decide whether to offer the button at all."""
    monkeypatch.setattr(settings, "vapid_public_key", "")
    monkeypatch.setattr(settings, "vapid_private_key", "")
    r = TestClient(create_app()).get("/api/v1/alerts/vapid-key")
    assert r.status_code == 503
