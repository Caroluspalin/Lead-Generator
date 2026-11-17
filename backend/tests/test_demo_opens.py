"""Demoavausten tuonti R2:sta (POST /leads/sync-opens): tenant-isolaatio, idempotenssi, throttle, vääränmuotoiset avaimet."""
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app import main
from app.demo_publish import parse_open_key
from tests.test_demo_publish import CONFIG, FakeStore, _publish, demo  # noqa: F401  (demo-fixture)

T0 = datetime(2026, 11, 17, 12, 32, tzinfo=timezone.utc)
SLOT = int(T0.timestamp() // 600)


class OpensStore(FakeStore):
    def __init__(self) -> None:
        super().__init__()
        self.opens: dict[str, datetime] = {}
        self.fail_list = False

    def list_objects(self, prefix: str) -> list[tuple[str, datetime]]:
        if self.fail_list:
            raise RuntimeError("R2 down")
        return [(k, v) for k, v in self.opens.items() if k.startswith(prefix)]

    def delete(self, key: str) -> None:
        self.opens.pop(key, None)
        super().delete(key)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[OpensStore]:
    fake = OpensStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: fake)
    main._last_opens_sync.clear()
    yield fake
    main._last_opens_sync.clear()


def _path(published: dict[str, Any]) -> str:
    return published["public_url"].rsplit("/", 1)[1]


def _lead(client: TestClient, lead_id: int) -> dict[str, Any]:
    return next(lead for lead in client.get("/leads").json() if lead["id"] == lead_id)


def test_parse_open_key() -> None:
    rec = parse_open_key(f"opens/abc-k7x2m/{SLOT}-mobile", T0)
    assert rec is not None and (rec.path, rec.slot, rec.device, rec.opened_at) == ("abc-k7x2m", SLOT, "mobile", T0)
    for bad in ("opens/x", f"opens/x/{SLOT}-tablet", "opens/x/abc-desktop", "demos/x/1-desktop", "opens//1-desktop"):
        assert parse_open_key(bad, T0) is None, bad


def test_sync_imports_opens_and_shows_on_lead(client_a: TestClient, store: OpensStore, demo: dict[str, Any]) -> None:
    published = _publish(client_a, demo)
    path = _path(published)
    store.opens[f"opens/{path}/{SLOT}-desktop"] = T0
    store.opens[f"opens/{path}/{SLOT + 1}-mobile"] = T0 + timedelta(minutes=14)

    res = client_a.post("/leads/sync-opens")
    assert res.status_code == 200
    assert res.json()["new_opens"] == [{"lead_id": demo["lead_id"], "name": demo["lead"]["name"], "count": 2}]
    assert store.opens == {}

    lead = _lead(client_a, demo["lead_id"])
    assert lead["demo_open_count"] == 2
    assert lead["demo_last_opened_at"].startswith("2026-11-17T12:46")


def test_leads_without_opens_default_to_zero(client_a: TestClient, demo: dict[str, Any]) -> None:
    lead = _lead(client_a, demo["lead_id"])
    assert lead["demo_open_count"] == 0 and lead["demo_last_opened_at"] is None


def test_sync_is_idempotent_and_dedups_same_slot(client_a: TestClient, store: OpensStore, demo: dict[str, Any]) -> None:
    path = _path(_publish(client_a, demo))
    key = f"opens/{path}/{SLOT}-desktop"
    store.opens[key] = T0
    assert len(client_a.post("/leads/sync-opens").json()["new_opens"]) == 1

    # Worker kirjoittaa saman ämpärin uudelleen: ei uutta avausta
    main._last_opens_sync.clear()
    store.opens[key] = T0 + timedelta(minutes=3)
    assert client_a.post("/leads/sync-opens").json()["new_opens"] == []
    assert store.opens == {}
    assert _lead(client_a, demo["lead_id"])["demo_open_count"] == 1


def test_sync_is_throttled(client_a: TestClient, store: OpensStore, demo: dict[str, Any]) -> None:
    path = _path(_publish(client_a, demo))
    assert client_a.post("/leads/sync-opens").json()["new_opens"] == []
    store.opens[f"opens/{path}/{SLOT}-desktop"] = T0
    assert client_a.post("/leads/sync-opens").json()["new_opens"] == []
    assert len(store.opens) == 1
    main._last_opens_sync.clear()
    assert len(client_a.post("/leads/sync-opens").json()["new_opens"]) == 1


def test_tenant_isolation(client_a: TestClient, client_b: TestClient, store: OpensStore, demo: dict[str, Any]) -> None:
    path = _path(_publish(client_a, demo))
    key = f"opens/{path}/{SLOT}-desktop"
    store.opens[key] = T0

    # B:n synkka ei tuo eikä poista A:n avauksia
    assert client_b.post("/leads/sync-opens").json()["new_opens"] == []
    assert key in store.opens
    assert all(lead["demo_open_count"] == 0 for lead in client_b.get("/leads").json())

    main._last_opens_sync.clear()
    assert len(client_a.post("/leads/sync-opens").json()["new_opens"]) == 1
    assert client_b.get("/leads").json() == []


def test_unknown_and_malformed_keys_are_left_alone(client_a: TestClient, store: OpensStore, demo: dict[str, Any]) -> None:
    path = _path(_publish(client_a, demo))
    store.opens[f"opens/ei-olemassa-k7x2m/{SLOT}-desktop"] = T0
    store.opens[f"opens/{path}/{SLOT}-tablet"] = T0
    assert client_a.post("/leads/sync-opens").json()["new_opens"] == []
    assert len(store.opens) == 2
    assert _lead(client_a, demo["lead_id"])["demo_open_count"] == 0


def test_r2_failure_is_502_and_retryable(client_a: TestClient, store: OpensStore, demo: dict[str, Any]) -> None:
    store.fail_list = True
    assert client_a.post("/leads/sync-opens").status_code == 502
    store.fail_list = False
    assert client_a.post("/leads/sync-opens").status_code == 200


def test_not_configured_is_empty(client_a: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    main._last_opens_sync.clear()
    monkeypatch.setattr("app.main.get_object_store", lambda: None)
    assert client_a.post("/leads/sync-opens").json() == {"new_opens": [], "new_quote_opens": [], "accepted_quotes": []}


def test_deleting_demo_removes_its_opens(client_a: TestClient, store: OpensStore, demo: dict[str, Any]) -> None:
    path = _path(_publish(client_a, demo))
    store.opens[f"opens/{path}/{SLOT}-desktop"] = T0
    client_a.post("/leads/sync-opens")
    assert client_a.delete(f"/leads/{demo['lead_id']}/demo").status_code == 200
    assert _lead(client_a, demo["lead_id"])["demo_open_count"] == 0
