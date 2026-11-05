"""Sähköposti- ja puhelinskriptigenerointi: profiili, allekirjoitus, opt-out, te-muoto, kielletyt sanat, DNC."""
import logging
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from app.main import (
    OPT_OUT_LINE,
    build_signature,
    check_generated_text,
    describe_website_problem,
    email_subject,
    find_forbidden_words,
    strip_model_sign_off,
)
from app.models import Lead, SenderProfile
from tests.conftest import FakeOpenAI

JARGON = ("SSL", "HTTPS", "DNS", "viewport", "HTTP 5", "HTTP 4", "parked", "sertifikaat", "domain")
SIGNATURE = "Terveisin,\nPalin\n040 123 4567\nhttps://palin.fi"


# --- Havainnot ---

@pytest.mark.parametrize(
    ("status", "issue", "expected"),
    [
        ("BROKEN WEBSITE", "DNS not resolving", "Googlen kautta löytyvä nettisivuosoitteenne ei avaudu"),
        ("INSECURE", "SSL certificate expired", "kun avasin sivunne, selain varoitti, ettei yhteys ole turvallinen"),
        ("INSECURE", "SSL certificate hostname mismatch", "kun avasin sivunne, selain varoitti, ettei yhteys ole turvallinen"),
        ("NO WEBSITE", "social media only", "löysin teidät vain Facebookista, omaa nettisivua en löytänyt"),
        ("NO WEBSITE", None, "en löytänyt teille omaa nettisivua Googlesta"),
        ("BROKEN WEBSITE", "HTTP 503", "sivunne näytti virheilmoituksen, kun avasin sen"),
        ("BROKEN WEBSITE", "HTTP 404", 'Googlessa oleva linkki sivuillenne johtaa "sivua ei löydy" -ilmoitukseen'),
        ("NOT MOBILE", "no viewport meta", "sivunne ei mukaudu puhelimen näytölle"),
    ],
)
def test_describe_website_problem(status: str, issue: Optional[str], expected: str) -> None:
    assert describe_website_problem(status, issue) == expected


def test_describe_combined_issue() -> None:
    text = describe_website_problem("INSECURE", "no HTTPS; no viewport meta")
    assert text == 'selain merkitsee sivunne "ei turvallinen" -merkinnällä ja sivunne ei mukaudu puhelimen näytölle'


@pytest.mark.parametrize("status", ["UNKNOWN", "WEBSITE OK", None])
def test_unverified_status_is_never_described_as_problem(status: Optional[str]) -> None:
    assert describe_website_problem(status, "HTTP 403") is None


@pytest.mark.parametrize(
    "issue",
    ["DNS not resolving", "SSL certificate expired", "no HTTPS; no viewport meta", "HTTP 500", "parked domain", "social media only"],
)
def test_observations_have_no_jargon_and_no_guessing(issue: str) -> None:
    text = describe_website_problem("BROKEN WEBSITE", issue) or ""
    assert text
    assert not any(term.lower() in text.lower() for term in JARGON)
    assert "saattaa" not in text


# --- Kielletyt sanat ---

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Teillä on ihana salonki.", ["ihana"]),
        ("Ihanaa päivää!", ["ihana"]),
        ("Upeat kuvat ja mahtavaa palvelua", ["upea", "mahtava"]),
        ("Tarjoamme kokonaisvaltaisen ratkaisun", ["ratkaisu", "kokonaisvaltainen"]),
        ("Vahvistetaan digitaalista läsnäoloanne", ["digitaalinen läsnäolo"]),
        ("Nostetaan sivunne seuraavalle tasolle", ["nostaa seuraavalle tasolle"]),
        ("Voisimme keskustella asiasta tarkemmin?", ["keskustella tarkemmin"]),
        ("Sivunne saattaa olla rikki", ["saattaa (arvailu)"]),
    ],
)
def test_find_forbidden_words(text: str, expected: list[str]) -> None:
    assert find_forbidden_words(text) == expected


@pytest.mark.parametrize(
    "text",
    ["Tämä on ihan nopea korjaus.", "Voin katsoa sen teille.", "Ratkaisen vian.", "Kiinnostaisiko?"],
)
def test_clean_text_has_no_forbidden_words(text: str) -> None:
    assert find_forbidden_words(text) == []


def test_check_generated_text_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.main"):
        warnings = check_generated_text(
            "Teillä on upea salonki. Hinta on 300 €.", kind="sähköposti", lead_id=7, model="m", max_words=90
        )
    assert warnings == ["kielletyt sanat: upea", "tekstissä mainitaan hinta"]
    assert "Generoitu sähköposti (liidi 7, m): kielletyt sanat: upea" in caplog.text


def test_check_generated_text_flags_too_long() -> None:
    warnings = check_generated_text("sana " * 130, kind="sähköposti", lead_id=1, model="m", max_words=90)
    assert warnings == ["liian pitkä: 130 sanaa (tavoite ~90)"]


def test_check_generated_text_clean_text_no_warnings(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.main"):
        assert check_generated_text("Hei, voin katsoa sen teille.", kind="x", lead_id=1, model="m", max_words=90) == []
    assert caplog.text == ""


# --- Allekirjoitus ---

def _profile(**overrides: Any) -> SenderProfile:
    data: dict[str, Any] = {"user_id": "u", "name": "Palin", "short_intro": "teen nettisivuja", **overrides}
    return SenderProfile(**data)


def test_signature_from_profile() -> None:
    assert build_signature(_profile()) == "Palin"
    assert build_signature(_profile(company_name="Palin Web", phone="040 1", website="https://palin.fi")) == (
        "Palin\nPalin Web\n040 1\nhttps://palin.fi"
    )


@pytest.mark.parametrize(
    "model_text",
    [
        "Hei,\n\nViesti.\n\nYstävällisin terveisin,\n[Nimesi]",
        "Hei,\n\nViesti.\n\nTerveisin,\nPalin",
        "Hei,\n\nViesti.\n\nParhain terveisin\nPalin\nPalin Web",
        "Hei,\n\nViesti.\n",
    ],
)
def test_model_sign_off_is_stripped(model_text: str) -> None:
    assert strip_model_sign_off(model_text) == "Hei,\n\nViesti."


# --- Subject ---

@pytest.mark.parametrize(
    ("status", "issue", "subject"),
    [
        ("NO WEBSITE", None, "Kysymys nettisivuista"),
        ("NO WEBSITE", "social media only", "Löysin teidät Facebookista"),
        ("BROKEN WEBSITE", "DNS not resolving", "Nettisivunne ei aukea"),
        ("BROKEN WEBSITE", "HTTP 500", "Huomasin jotain sivuistanne"),
        ("INSECURE", "SSL certificate expired", "Huomasin jotain sivuistanne"),
        ("NOT MOBILE", "no viewport meta", "Sivunne puhelimella"),
        ("UNKNOWN", "HTTP 403", "Kysymys nettisivuistanne"),
        ("WEBSITE OK", None, "Kysymys nettisivuistanne"),
    ],
)
def test_email_subject_is_short_and_natural(status: str, issue: Optional[str], subject: str) -> None:
    lead = Lead(user_id="u", name="Kampaamo Nyberg Harri", city="Kauniainen", website_status=status, website_issue=issue)
    assert email_subject(lead) == subject
    assert "Kampaamo" not in subject
    assert len(subject) <= 40


# --- Sähköposti endpointin kautta ---

def _user_prompt(fake: type[FakeOpenAI]) -> str:
    return str(fake.calls[-1]["messages"][1]["content"])


def _system_prompt(fake: type[FakeOpenAI]) -> str:
    return str(fake.calls[-1]["messages"][0]["content"])


def test_email_requires_sender_profile(client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI]) -> None:
    lead = make_lead(website_status="NO WEBSITE")
    res = client_a.post(f"/leads/{lead['id']}/generate-email", json={})
    assert res.status_code == 428
    assert "Sender profile missing" in res.json()["detail"]
    assert fake_openai.calls == []


def test_call_script_requires_sender_profile(client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI]) -> None:
    lead = make_lead(website_status="NO WEBSITE")
    assert client_a.post(f"/leads/{lead['id']}/generate-call-script").status_code == 428
    assert fake_openai.calls == []


def test_email_always_has_signature_and_opt_out(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    fake_openai.reply = "Hei,\n\nOlen Palin. Löysin teidät vain Facebookista.\n\nYstävällisin terveisin,\n[Nimesi]\n"
    lead = make_lead(website_status="NO WEBSITE", website_issue="social media only")
    body = client_a.post(f"/leads/{lead['id']}/generate-email", json={}).json()["body"]
    assert body == f"Hei,\n\nOlen Palin. Löysin teidät vain Facebookista.\n\n{SIGNATURE}\n\n{OPT_OUT_LINE}"
    assert body.count("terveisin") + body.count("Terveisin") == 1
    drafts = client_a.get(f"/leads/{lead['id']}/drafts").json()
    assert drafts[0]["body"] == body


def test_email_prompt_contains_profile_observation_and_offer(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead = make_lead(
        name="Kampaamo Nyberg Harri", city="Kauniainen", primary_type="hair_salon",
        website_status="BROKEN WEBSITE", website_issue="DNS not resolving",
    )
    client_a.post(f"/leads/{lead['id']}/generate-email", json={})
    prompt = _user_prompt(fake_openai)
    assert "- Nimi: Palin" in prompt
    assert "- Esittely: teen nettisivuja paikallisille yrityksille pääkaupunkiseudulla" in prompt
    assert "(ei yritysnimeä, esiinny omalla nimellä)" in prompt
    assert "HAVAINTO (varma, tein sen itse): Googlen kautta löytyvä nettisivuosoitteenne ei avaudu" in prompt
    assert "TARJOUS: Voin katsoa, mistä vika johtuu" in prompt
    assert "hair_salon" in prompt and "Kauniainen" in prompt
    assert "DNS" not in prompt


def test_email_system_prompt_rules(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead = make_lead(website_status="NO WEBSITE")
    client_a.post(f"/leads/{lead['id']}/generate-email", json={})
    system = _system_prompt(fake_openai)
    assert "Te-muoto johdonmukaisesti" in system
    assert "Ei koskaan sinä-muotoa" in system
    assert "kuka olen ja miten löysin yrityksen" in system
    assert "enintään noin 90 sanaa" in system
    assert "keskustelua tarkemmin" in system
    for word in ("ihana", "upea", "mahtava", "ainutlaatuinen", "intohimo", "ratkaisu", "kokonaisvaltainen",
                 "digitaalinen läsnäolo", "nostaa seuraavalle tasolle"):
        assert word in system
    assert "ÄLÄ kirjoita lopputervehdystä, allekirjoitusta" in system


def test_email_no_website_offers_free_draft(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead = make_lead(website_status="NO WEBSITE")
    client_a.post(f"/leads/{lead['id']}/generate-email", json={})
    assert "TARJOUS: Voin tehdä teille ilmaisen luonnoksen" in _user_prompt(fake_openai)


def test_email_unknown_status_forbids_claiming_problem(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead = make_lead(website_status="UNKNOWN", website_issue="HTTP 403")
    client_a.post(f"/leads/{lead['id']}/generate-email", json={})
    prompt = _user_prompt(fake_openai)
    assert "ei varmistettua ongelmaa" in prompt
    assert "403" not in prompt


def test_forbidden_word_in_generated_email_logs_warning(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_openai.reply = "Hei, teillä on ihana salonki ja upeat kuvat."
    lead = make_lead(website_status="NO WEBSITE")
    with caplog.at_level(logging.WARNING, logger="app.main"):
        res = client_a.post(f"/leads/{lead['id']}/generate-email", json={})
    assert res.status_code == 200  # varoitus ei estä
    assert f"Generoitu sähköposti (liidi {lead['id']}, gpt-4o-mini-test): kielletyt sanat: ihana, upea" in caplog.text


def test_opt_out_line_wording() -> None:
    assert "ei kiitos" in OPT_OUT_LINE
    assert "en ota enää yhteyttä" in OPT_OUT_LINE


# --- Puhelinskripti ---

def test_call_script(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    fake_openai.reply = "1. Avaus: Hei, Palin täällä."
    lead = make_lead(website_status="INSECURE", website_issue="SSL certificate hostname mismatch", rating=5.0, review_count=10)
    res = client_a.post(f"/leads/{lead['id']}/generate-call-script")
    assert res.status_code == 200
    assert res.json() == {"script": "1. Avaus: Hei, Palin täällä.", "model": "gpt-4o-mini-test"}

    call = fake_openai.calls[-1]
    system = call["messages"][0]["content"]
    for heading in ("1. Avaus", "2. Havainto", "3. Tarjous", '4. Jos "ei kiinnosta"', "5. Jos kysyvät hintaa"):
        assert heading in system
    assert "Onko teillä hetki, vai soitanko myöhemmin?" in system
    assert "Selvä, kiitos ajastanne, mukavaa päivää!" in system
    assert "ÄLÄ mainitse mitään euromääriä" in system
    assert "EI konsulttimaisia kysymyksiä" in system
    assert "Te-muoto johdonmukaisesti" in system
    prompt = call["messages"][1]["content"]
    assert "- Nimi: Palin" in prompt
    assert "selain varoitti" in prompt
    assert "SSL" not in prompt


def test_call_script_does_not_scrape(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
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
    client_a: TestClient, dnc_lead: dict[str, Any], fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any], path: str
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
    res = client_b.post("/send-email", json={"to": "omistaja@carmen.fi", "subject": "S", "body": "B"})
    assert res.status_code == 500
    assert "SMTP not configured" in res.json()["detail"]


def test_send_email_with_other_users_lead_id_is_404(client_b: TestClient, dnc_lead: dict[str, Any]) -> None:
    res = client_b.post("/send-email", json={"to": "x@y.fi", "subject": "S", "body": "B", "lead_id": dnc_lead["id"]})
    assert res.status_code == 404


def test_unmarking_do_not_contact_allows_generation_again(
    client_a: TestClient, dnc_lead: dict[str, Any], fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    client_a.patch(f"/leads/{dnc_lead['id']}", json={"do_not_contact": False})
    assert client_a.post(f"/leads/{dnc_lead['id']}/generate-email", json={}).status_code == 200
