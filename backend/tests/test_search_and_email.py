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
    assert len(results) == 5
    assert all(r["discovery_method"] == "DEV-MOCK" for r in results)
    assert all("Espoo" in r["address"] for r in results)

    history = client_a.get("/search-history").json()
    assert len(history) == 1
    assert history[0]["business_type"] == "parturi"
    assert history[0]["city"] == "Espoo"
    assert history[0]["result_count"] == 5


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
