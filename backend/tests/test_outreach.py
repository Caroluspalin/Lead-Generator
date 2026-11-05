"""Sähköposti- ja puhelinskriptigenerointi: havaittu ongelma selkokielellä, opt-out, do_not_contact."""
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from app.main import OPT_OUT_LINE, describe_website_problem
from tests.conftest import FakeOpenAI

JARGON = ("SSL", "HTTPS", "DNS", "viewport", "HTTP 5", "HTTP 4", "parked")


# --- Selkokielinen kuvaus ---

@pytest.mark.parametrize(
    ("status", "issue", "expected"),
    [
        ("BROKEN WEBSITE", "DNS not resolving", "Googlen kautta löytyvä nettisivuosoite ei enää avaudu"),
        ("INSECURE", "SSL certificate expired", "selain näyttää kävijöille turvallisuusvaroituksen ennen sivulle pääsyä"),
        ("INSECURE", "SSL certificate hostname mismatch", "selain näyttää kävijöille turvallisuusvaroituksen ennen sivulle pääsyä"),
        ("NO WEBSITE", "social media only", "yrityksellä on vain somesivu (esim. Facebook), ei omaa nettisivua"),
        ("NO WEBSITE", None, "yrityksellä ei ole nettisivuja"),
        ("BROKEN WEBSITE", "HTTP 503", "nettisivu näyttää tällä hetkellä virheilmoituksen"),
        ("BROKEN WEBSITE", "HTTP 404", "Googlessa oleva linkki nettisivuille johtaa sivulle, jota ei löydy"),
        ("BROKEN WEBSITE", "parked domain", "nettisivuosoitteessa ei ole enää yrityksen omaa sivua"),
        ("NOT MOBILE", "no viewport meta", "sivusto ei mukaudu puhelimen näytölle"),
    ],
)
def test_describe_website_problem(status: str, issue: Optional[str], expected: str) -> None:
    assert describe_website_problem(status, issue) == expected


def test_describe_combined_issue() -> None:
    text = describe_website_problem("INSECURE", "no HTTPS; no viewport meta")
    assert text is not None
    assert "suojattua yhteyttä" in text and "puhelimen näytölle" in text


@pytest.mark.parametrize("status", ["UNKNOWN", "WEBSITE OK", None])
def test_unverified_status_is_never_described_as_problem(status: Optional[str]) -> None:
    assert describe_website_problem(status, "HTTP 403") is None


@pytest.mark.parametrize(
    "issue",
    ["DNS not resolving", "SSL certificate expired", "no HTTPS; no viewport meta", "HTTP 500", "parked domain"],
)
def test_descriptions_contain_no_jargon(issue: str) -> None:
    text = describe_website_problem("BROKEN WEBSITE", issue) or ""
    assert not any(term.lower() in text.lower() for term in JARGON)


# --- Sähköposti ---

def _user_prompt(fake: type[FakeOpenAI]) -> str:
    return str(fake.calls[-1]["messages"][1]["content"])


def _system_prompt(fake: type[FakeOpenAI]) -> str:
    return str(fake.calls[-1]["messages"][0]["content"])


def test_email_uses_plain_language_issue(client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI]) -> None:
    lead = make_lead(website_status="BROKEN WEBSITE", website_issue="DNS not resolving")
    assert client_a.post(f"/leads/{lead['id']}/generate-email", json={}).status_code == 200
    prompt = _user_prompt(fake_openai)
    assert "Havaittu ongelma: Googlen kautta löytyvä nettisivuosoite ei enää avaudu" in prompt
    assert "DNS" not in prompt


def test_email_unknown_status_forbids_claiming_problem(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI]
) -> None:
    lead = make_lead(website_status="UNKNOWN", website_issue="HTTP 403")
    client_a.post(f"/leads/{lead['id']}/generate-email", json={})
    prompt = _user_prompt(fake_openai)
    assert "ei varmistettua ongelmaa" in prompt
    assert "403" not in prompt


def test_email_system_prompt_bans_jargon_and_fear(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI]
) -> None:
    lead = make_lead(website_status="NO WEBSITE")
    client_a.post(f"/leads/{lead['id']}/generate-email", json={})
    system = _system_prompt(fake_openai)
    assert "EI teknistä jargonia" in system
    assert "EI liioittelua eikä pelottelua" in system


def test_email_always_ends_with_opt_out(client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI]) -> None:
    fake_openai.reply = "Hei!\n\nHuomasin, että teillä on vain Facebook-sivu.\n\n"
    lead = make_lead(website_status="NO WEBSITE", website_issue="social media only")
    body = client_a.post(f"/leads/{lead['id']}/generate-email", json={}).json()["body"]
    assert body.endswith(OPT_OUT_LINE)
    assert body == "Hei!\n\nHuomasin, että teillä on vain Facebook-sivu.\n\n" + OPT_OUT_LINE
    drafts = client_a.get(f"/leads/{lead['id']}/drafts").json()
    assert drafts[0]["body"].endswith(OPT_OUT_LINE)


def test_opt_out_line_wording() -> None:
    assert "ei kiitos" in OPT_OUT_LINE
    assert "en ota enää yhteyttä" in OPT_OUT_LINE


# --- Puhelinskripti ---

def test_call_script(client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI]) -> None:
    fake_openai.reply = "1. Esittely: Hei, [Nimesi] täällä [Yrityksesi]stä."
    lead = make_lead(website_status="INSECURE", website_issue="SSL certificate hostname mismatch", rating=5.0, review_count=10)
    res = client_a.post(f"/leads/{lead['id']}/generate-call-script")
    assert res.status_code == 200
    assert res.json() == {"script": "1. Esittely: Hei, [Nimesi] täällä [Yrityksesi]stä.", "model": "gpt-4o-mini-test"}

    call = fake_openai.calls[-1]
    assert call["model"] == "gpt-4o-mini"
    system = call["messages"][0]["content"]
    for heading in ("1. Esittely", "2. Havainto", "3. Kysymys", "4. Ehdotus", '5. Jos "ei kiinnosta"'):
        assert heading in system
    prompt = call["messages"][1]["content"]
    assert "turvallisuusvaroituksen" in prompt
    assert "SSL" not in prompt


def test_call_script_does_not_scrape(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], monkeypatch: pytest.MonkeyPatch
) -> None:
    scraped: list[str] = []
    monkeypatch.setattr("app.main.scrape_website_text", lambda url: scraped.append(url))
    lead = make_lead(website="www.carmen.fi", website_status="UNKNOWN")
    assert client_a.post(f"/leads/{lead['id']}/generate-call-script").status_code == 200
    assert scraped == []


def test_call_script_other_users_lead_is_404(
    client_b: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI]
) -> None:
    lead = make_lead()
    assert client_b.post(f"/leads/{lead['id']}/generate-call-script").status_code == 404
    assert fake_openai.calls == []


# --- do_not_contact ---

@pytest.fixture
def dnc_lead(client_a: TestClient, make_lead: Any) -> dict[str, Any]:
    lead = make_lead(website_status="NO WEBSITE")
    client_a.patch(f"/leads/{lead['id']}", json={"email": "Omistaja@Carmen.fi", "do_not_contact": True})
    return lead


@pytest.mark.parametrize("path", ["generate-email", "generate-call-script"])
def test_do_not_contact_blocks_generation(
    client_a: TestClient, dnc_lead: dict[str, Any], fake_openai: type[FakeOpenAI], path: str
) -> None:
    res = client_a.post(f"/leads/{dnc_lead['id']}/{path}", json={})
    assert res.status_code == 409
    assert fake_openai.calls == []


def test_do_not_contact_blocks_sending_by_lead_id(
    client_a: TestClient, dnc_lead: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.SMTP_HOST", "smtp.test")
    res = client_a.post("/send-email", json={"to": "joku@muu.fi", "subject": "S", "body": "B", "lead_id": dnc_lead["id"]})
    assert res.status_code == 409


def test_do_not_contact_blocks_sending_by_address(client_a: TestClient, dnc_lead: dict[str, Any]) -> None:
    res = client_a.post("/send-email", json={"to": " omistaja@carmen.FI ", "subject": "S", "body": "B"})
    assert res.status_code == 409


def test_other_users_do_not_contact_does_not_block(client_b: TestClient, dnc_lead: dict[str, Any]) -> None:
    # B:n lähetys samaan osoitteeseen ei esty A:n merkinnällä (kaatuu vasta puuttuvaan SMTP-konfiguraatioon)
    res = client_b.post("/send-email", json={"to": "omistaja@carmen.fi", "subject": "S", "body": "B"})
    assert res.status_code == 500
    assert "SMTP not configured" in res.json()["detail"]


def test_send_email_with_other_users_lead_id_is_404(client_b: TestClient, dnc_lead: dict[str, Any]) -> None:
    res = client_b.post("/send-email", json={"to": "x@y.fi", "subject": "S", "body": "B", "lead_id": dnc_lead["id"]})
    assert res.status_code == 404


def test_unmarking_do_not_contact_allows_generation_again(
    client_a: TestClient, dnc_lead: dict[str, Any], fake_openai: type[FakeOpenAI]
) -> None:
    client_a.patch(f"/leads/{dnc_lead['id']}", json={"do_not_contact": False})
    assert client_a.post(f"/leads/{dnc_lead['id']}/generate-email", json={}).status_code == 200
