"""User B ei saa nähdä, muokata eikä poistaa user A:n dataa. Odotettu 404, ei 403."""
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import EmailDraft, SearchHistoryEntry


def test_b_does_not_see_a_leads(client_b: TestClient, make_lead: Any) -> None:
    make_lead()
    assert client_b.get("/leads").json() == []


def test_b_cannot_update_a_lead(client_a: TestClient, client_b: TestClient, make_lead: Any) -> None:
    lead = make_lead()
    res = client_b.patch(f"/leads/{lead['id']}", json={"pipeline_status": "Rejected"})
    assert res.status_code == 404
    assert client_a.get("/leads").json()[0]["pipeline_status"] == "Shortlisted"


def test_b_cannot_delete_a_lead(client_a: TestClient, client_b: TestClient, make_lead: Any) -> None:
    lead = make_lead()
    assert client_b.delete(f"/leads/{lead['id']}").status_code == 404
    assert len(client_a.get("/leads").json()) == 1


def test_b_cannot_read_a_drafts(
    client_a: TestClient, client_b: TestClient, make_lead: Any, session: Session
) -> None:
    lead = make_lead()
    session.add(EmailDraft(user_id="user-a", lead_id=lead["id"], subject="S", body="B", model="m"))
    session.commit()

    assert len(client_a.get(f"/leads/{lead['id']}/drafts").json()) == 1
    assert client_b.get(f"/leads/{lead['id']}/drafts").status_code == 404


def test_b_cannot_generate_email_for_a_lead(client_b: TestClient, make_lead: Any, monkeypatch: Any) -> None:
    lead = make_lead()
    monkeypatch.setattr("app.main.OPENAI_API_KEY", "sk-test")
    assert client_b.post(f"/leads/{lead['id']}/generate-email", json={}).status_code == 404


def test_b_does_not_see_a_search_history(client_a: TestClient, client_b: TestClient) -> None:
    client_a.get("/search", params={"business_type": "parturi", "city": "Espoo"})
    assert len(client_a.get("/search-history").json()) == 1
    assert client_b.get("/search-history").json() == []


def test_b_cannot_delete_a_search_history(
    client_a: TestClient, client_b: TestClient, session: Session
) -> None:
    client_a.get("/search", params={"business_type": "parturi", "city": "Espoo"})
    entry_id = client_a.get("/search-history").json()[0]["id"]

    assert client_b.delete(f"/search-history/{entry_id}").status_code == 404
    assert session.exec(select(SearchHistoryEntry)).first() is not None
    assert client_a.delete(f"/search-history/{entry_id}").json() == {"ok": True}
