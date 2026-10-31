"""Route alert subscriptions without an account.

Riders get alerts with one tap and no sign-up, so for push the browser's push
endpoint is the subscriber's identity. No DB here: the service layer is faked,
and what's checked is who each request is attributed to.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import SubscribeResponse
from app.services import alerts_service

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc",
       "keys": {"p256dh": "BPk...", "auth": "k9..."}}
RIDER = alerts_service.push_subscriber_id(SUB["endpoint"])


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def calls(monkeypatch):
    seen = []

    async def subscribe(db, user_id, req):
        seen.append(("subscribe", user_id, req.route_id))
        return SubscribeResponse(id="s1", route_id=req.route_id,
                                 channel=req.channel, created=True)

    async def unsubscribe(db, user_id, route_id):
        seen.append(("unsubscribe", user_id, route_id))
        return True

    monkeypatch.setattr(alerts_service, "subscribe", subscribe)
    monkeypatch.setattr(alerts_service, "unsubscribe", unsubscribe)
    return seen


def test_a_riders_id_is_stable_and_fits_the_column():
    assert RIDER == alerts_service.push_subscriber_id(SUB["endpoint"])
    assert RIDER.startswith("push:") and len(RIDER) == 64
    assert RIDER != alerts_service.push_subscriber_id(SUB["endpoint"] + "x")


def test_push_alerts_need_no_account(client, calls):
    r = client.post("/api/v1/alerts/subscribe",
                    json={"route_id": "r1", "channel": "push", "push_subscription": SUB})
    assert r.status_code == 200
    assert calls == [("subscribe", RIDER, "r1")]


def test_in_app_alerts_still_need_an_account(client, calls):
    """channel='web' has no way to reach anyone but an account."""
    for body in ({"route_id": "r1", "channel": "web"},
                 {"route_id": "r1", "channel": "web", "push_subscription": SUB}):
        assert client.post("/api/v1/alerts/subscribe", json=body).status_code == 401
    assert calls == []


def test_stopping_alerts_also_goes_by_push_endpoint(client, calls):
    r = client.post("/api/v1/alerts/unsubscribe",
                    json={"route_id": "r1", "endpoint": SUB["endpoint"]})
    assert r.status_code == 200 and r.json() == {"removed": True}
    assert calls == [("unsubscribe", RIDER, "r1")]
