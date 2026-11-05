import csv
import io
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.scoring import lead_score


def test_create_lead_sets_owner_and_defaults(client_a: TestClient) -> None:
    res = client_a.post(
        "/leads",
        json={"name": "Parturi Testi", "city": "Espoo", "google_place_id": "p1", "user_id": "hacker"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] is not None
    # user_id tulee tokenista, ei clientin syötteestä
    assert body["user_id"] == "user-a"
    assert body["pipeline_status"] == "Shortlisted"


def test_list_leads(client_a: TestClient, make_lead: Any) -> None:
    make_lead(name="Eka")
    make_lead(name="Toka")
    res = client_a.get("/leads")
    assert res.status_code == 200
    assert {lead["name"] for lead in res.json()} == {"Eka", "Toka"}


def test_update_lead(client_a: TestClient, make_lead: Any) -> None:
    lead = make_lead()
    res = client_a.patch(f"/leads/{lead['id']}", json={"pipeline_status": "Contacted", "notes": "soitettu"})
    assert res.status_code == 200
    body = res.json()
    assert body["pipeline_status"] == "Contacted"
    assert body["notes"] == "soitettu"
    assert body["name"] == lead["name"]


def test_update_lead_bumps_updated_at(
    client_a: TestClient, make_lead: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead = make_lead()
    later = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.main.utc_now", lambda: later)

    res = client_a.patch(f"/leads/{lead['id']}", json={"notes": "päivitetty"})
    assert res.status_code == 200
    body = res.json()
    assert body["updated_at"].startswith("2030-01-01T12:00:00")
    assert body["created_at"] == lead["created_at"]


def test_delete_lead(client_a: TestClient, make_lead: Any) -> None:
    lead = make_lead()
    assert client_a.delete(f"/leads/{lead['id']}").json() == {"ok": True}
    assert client_a.get("/leads").json() == []
    assert client_a.delete(f"/leads/{lead['id']}").status_code == 404


def test_duplicate_place_id_blocked_for_same_user(client_a: TestClient, make_lead: Any) -> None:
    make_lead(google_place_id="dup-1")
    res = client_a.post("/leads", json={"name": "Sama", "city": "Espoo", "google_place_id": "dup-1"})
    assert res.status_code == 400
    assert len(client_a.get("/leads").json()) == 1


def test_same_place_id_allowed_for_different_users(client_b: TestClient, make_lead: Any) -> None:
    make_lead(google_place_id="shared-1")
    make_lead(client=client_b, google_place_id="shared-1")
    assert len(client_b.get("/leads").json()) == 1


def test_csv_export_only_own_leads(client_a: TestClient, client_b: TestClient, make_lead: Any) -> None:
    own = make_lead(name="Oma Liidi")
    foreign = make_lead(client=client_b, name="Vieras Liidi")

    res = client_a.get(f"/leads/export?ids={own['id']},{foreign['id']}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")

    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[0][0] == "ID"
    assert [row[1] for row in rows[1:]] == ["Oma Liidi"]


def test_csv_export_requires_valid_ids(client_a: TestClient) -> None:
    assert client_a.get("/leads/export?ids=abc").status_code == 400


def test_create_lead_stores_places_fields_and_server_side_score(client_a: TestClient) -> None:
    res = client_a.post("/leads", json={
        "name": "Parturi Pisteet",
        "city": "Kauniainen",
        "google_place_id": "ChIJ-score",
        "website_status": "NO WEBSITE",
        "rating": 4.6,
        "review_count": 120,
        "business_status": "OPERATIONAL",
        "primary_type": "hair_salon",
        "maps_url": "https://maps.google.com/?cid=9",
        "lead_score": 1,
    })
    assert res.status_code == 200
    body = res.json()
    assert body["rating"] == 4.6
    assert body["review_count"] == 120
    assert body["business_status"] == "OPERATIONAL"
    assert body["primary_type"] == "hair_salon"
    assert body["maps_url"] == "https://maps.google.com/?cid=9"
    # Clientin lähettämä lead_score ohitetaan, serveri laskee
    assert body["lead_score"] == lead_score("NO WEBSITE", 4.6, 120, "OPERATIONAL")
    assert body["lead_score"] > 1
    assert client_a.get("/leads").json()[0]["lead_score"] == body["lead_score"]
