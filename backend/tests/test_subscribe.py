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
from app.services import alerts_service, push

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc",
       "keys": {"p256dh": push.generate_keys()[0], "auth": "AAAAAAAAAAAAAAAAAAAAAA"}}
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


def test_a_test_alert_goes_to_the_callers_own_subscription(client, monkeypatch):
    sent = []

    async def send_test(db, user_id, route_id):
        if route_id != "r1":
            raise LookupError("this browser doesn't follow that route")
        sent.append((user_id, route_id))
        return None

    monkeypatch.setattr(alerts_service, "send_test", send_test)
    monkeypatch.setattr("app.api.routes.alerts.push_enabled", lambda: True)
    ask = {"route_id": "r1", "endpoint": SUB["endpoint"]}
    r = client.post("/api/v1/alerts/test", json=ask)
    assert r.status_code == 200 and r.json() == {"sent": True, "status": None}
    assert sent == [(RIDER, "r1")]
    # A route this browser doesn't follow: nothing to send to.
    r = client.post("/api/v1/alerts/test", json={**ask, "route_id": "r2"})
    assert r.status_code == 404


def test_no_test_alert_promised_when_push_is_off(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.alerts.push_enabled", lambda: False)
    r = client.post("/api/v1/alerts/test",
                    json={"route_id": "r1", "endpoint": SUB["endpoint"]})
    assert r.status_code == 503
