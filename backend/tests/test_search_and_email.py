from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import EmailDraft, Lead


def test_search_mock_mode_returns_results_and_saves_history(client_a: TestClient) -> None:
    res = client_a.get("/search", params={"business_type": "parturi", "city": "Espoo"})
    assert res.status_code == 200
    results = res.json()
    assert len(results) == 7
    assert all(r["discovery_method"] == "DEV-MOCK" for r in results)
    assert all("Espoo" in r["address"] for r in results)
    assert all(r["maps_url"].startswith("https://www.google.com/maps/") for r in results)

    statuses = {r["business_status"] for r in results}
    assert "CLOSED_PERMANENTLY" not in statuses
    assert "CLOSED_TEMPORARILY" in statuses

    history = client_a.get("/search-history").json()
    assert len(history) == 1
    assert history[0]["business_type"] == "parturi"
    assert history[0]["city"] == "Espoo"
    assert history[0]["result_count"] == 7


class _FakeOpenAI:
    """Korvaa openai.OpenAI:n. Tallentaa saadut viestit tarkistusta varten."""

    calls: list[dict[str, Any]] = []

    def __init__(self, api_key: str) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        _FakeOpenAI.calls.append(kwargs)
        return SimpleNamespace(
            model="gpt-4o-mini-test",
            choices=[SimpleNamespace(message=SimpleNamespace(content="  Hei, testiviesti.  "))],
        )


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch) -> type[_FakeOpenAI]:
    _FakeOpenAI.calls = []
    monkeypatch.setattr("app.main.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    return _FakeOpenAI


def test_generate_email_saves_draft(
    client_a: TestClient, make_lead: Any, fake_openai: type[_FakeOpenAI], session: Session
) -> None:
    lead = make_lead(website_status="NO WEBSITE")

    res = client_a.post(f"/leads/{lead['id']}/generate-email", json={"instruction": "lyhyempi"})
    assert res.status_code == 200
    body = res.json()
    assert body["body"] == "Hei, testiviesti."
    assert body["model"] == "gpt-4o-mini-test"
    assert lead["name"] in body["subject"]

    drafts = session.exec(select(EmailDraft)).all()
    assert len(drafts) == 1
    assert drafts[0].user_id == "user-a"
    assert drafts[0].lead_id == lead["id"]
    assert drafts[0].body == "Hei, testiviesti."

    assert len(client_a.get(f"/leads/{lead['id']}/drafts").json()) == 1
    assert "lyhyempi" in fake_openai.calls[0]["messages"][1]["content"]


def test_generate_email_caches_deep_scan_context(
    client_a: TestClient,
    make_lead: Any,
    fake_openai: type[_FakeOpenAI],
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.main.scrape_website_text", lambda _url: "Tarjoamme parturipalveluita.")
    lead = make_lead(website="www.example.fi", website_status="NOT MOBILE")

    assert client_a.post(f"/leads/{lead['id']}/generate-email", json={}).status_code == 200

    db_lead = session.get(Lead, lead["id"])
    assert db_lead is not None
    assert db_lead.website_context == "Tarjoamme parturipalveluita."
    assert db_lead.scraped_at is not None
    assert "Tarjoamme parturipalveluita." in fake_openai.calls[0]["messages"][1]["content"]


def test_generate_email_survives_scrape_failure(
    client_a: TestClient, make_lead: Any, fake_openai: type[_FakeOpenAI]
) -> None:
    # Oletus-mock (block_network) heittää poikkeuksen -> meili generoidaan ilman personointia
    lead = make_lead(website="www.example.fi", website_status="BROKEN WEBSITE")
    assert client_a.post(f"/leads/{lead['id']}/generate-email", json={}).status_code == 200


def test_generate_email_without_api_key(client_a: TestClient, make_lead: Any) -> None:
    lead = make_lead()
    assert client_a.post(f"/leads/{lead['id']}/generate-email", json={}).status_code == 500


def test_search_live_path_wires_service_and_website_analysis(
    client_a: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.USE_LIVE_GOOGLE", True)
    monkeypatch.setattr("app.main.GOOGLE_API_KEY", "AIza-test")
    places = [
        {"place_id": "ChIJ1", "name": "Parturi A", "address": "Katu 1", "phone": None, "website": "https://a.fi",
         "rating": 4.5, "review_count": 30, "business_status": "OPERATIONAL", "primary_type": "hair_salon",
         "maps_url": "https://maps.google.com/?cid=1"},
        {"place_id": "ChIJ2", "name": "Parturi B", "address": "Katu 2", "phone": "09 1", "website": None,
         "rating": None, "review_count": None, "business_status": "CLOSED_TEMPORARILY", "primary_type": None,
         "maps_url": None},
    ]
    monkeypatch.setattr("app.main.GooglePlacesService.search_grid", lambda self, city, keyword: places)
    monkeypatch.setattr("app.main.analyze_website", lambda url: "NOT MOBILE" if url else "NO WEBSITE")

    res = client_a.get("/search", params={"business_type": "parturi", "city": "Kauniainen"})
    assert res.status_code == 200
    by_id = {r["place_id"]: r for r in res.json()}
    assert by_id["ChIJ1"]["website_status"] == "NOT MOBILE"
    assert by_id["ChIJ1"]["discovery_method"] == "API"
    assert by_id["ChIJ1"]["review_count"] == 30
    assert by_id["ChIJ2"]["website_status"] == "NO WEBSITE"
    assert client_a.get("/search-history").json()[0]["result_count"] == 2


def test_search_results_sorted_by_score_desc(client_a: TestClient) -> None:
    results = client_a.get("/search", params={"business_type": "parturi", "city": "Espoo"}).json()
    scores = [r["lead_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 100 for s in scores)
    assert results[0]["website_status"] == "NO WEBSITE"
    temp_closed = next(r for r in results if r["business_status"] == "CLOSED_TEMPORARILY")
    assert temp_closed["lead_score"] < results[0]["lead_score"]


def test_search_marks_already_saved_instead_of_hiding(
    client_a: TestClient, client_b: TestClient, make_lead: Any
) -> None:
    first = client_a.get("/search", params={"business_type": "parturi", "city": "Espoo"}).json()
    assert not any(r["already_saved"] for r in first)
    target = first[2]
    make_lead(name=target["name"], google_place_id=target["place_id"])

    again = client_a.get("/search", params={"business_type": "parturi", "city": "Espoo"}).json()
    assert len(again) == len(first)
    saved = [r["place_id"] for r in again if r["already_saved"]]
    assert saved == [target["place_id"]]

    # Toisen käyttäjän pipeline ei vaikuta
    other = client_b.get("/search", params={"business_type": "parturi", "city": "Espoo"}).json()
    assert not any(r["already_saved"] for r in other)
