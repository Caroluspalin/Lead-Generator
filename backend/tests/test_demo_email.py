"""Sähköposti julkaistun demon kanssa: rakenne per ongelmatyyppi, ei loppukysymystä, allekirjoitus, brand_name."""
import json
import re
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from app.main import (
    CUSTOMER_IMPACT_DEFAULT,
    DEMO_EMAIL_MAX_WORDS,
    DEMO_LINK_PARAGRAPH,
    DEMO_RISK_PARAGRAPH,
    OPT_OUT_LINE,
    build_demo_email_body,
    build_signature,
    clean_demo_paragraphs,
    customer_impact,
    demo_email_subject,
    display_website,
    email_head,
)
from app.models import Lead, SenderProfile
from app.text_quality import word_count
from tests.conftest import FakeOpenAI
from tests.test_demo_publish import CONFIG, FakeStore
from tests.test_demo_site import VALID

URL = "https://demo.palinweb.fi/taina-lantiainen-k7x2m"
MODEL_TEXT = (
    "Olen Palin ja teen nettisivuja paikallisille yrityksille. Etsin parturi-kampaamoja Kauniaisista "
    "ja löysin teidät Googlesta.\n\n"
    "Asiakas löytää teidät kartalta, mutta ei näe palveluitanne eikä aukioloaikoja, joten hänen pitää soittaa."
)


def _profile(**kw: Any) -> SenderProfile:
    base: dict[str, Any] = {"user_id": "u", "name": "Palin", "short_intro": "teen nettisivuja"}
    return SenderProfile(**{**base, **kw})


def _lead(status: str, issue: Optional[str] = None) -> Lead:
    return Lead(user_id="u", name="Parturi-Kampaamo Taina Lantiainen", city="Kauniainen", website_status=status, website_issue=issue)


# --- Allekirjoitus ---

@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({}, "Palin"),
        ({"brand_name": "Palin Web"}, "Palin\nPalin Web"),
        ({"website": "https://palinweb.fi/"}, "Palin\npalinweb.fi"),
        ({"phone": "040 123 4567"}, "Palin\n040 123 4567"),
        (
            {"brand_name": "Palin Web", "website": "https://www.palinweb.fi", "phone": "040 123 4567"},
            "Palin\nPalin Web · www.palinweb.fi\n040 123 4567",
        ),
        # brand_name voittaa virallisen nimen; ilman sitä company_name (vanhat profiilit)
        ({"brand_name": "Palin Web", "company_name": "Tmi Carolus Palin"}, "Palin\nPalin Web"),
        ({"company_name": "Tmi Carolus Palin", "website": "http://palin.fi"}, "Palin\nTmi Carolus Palin · palin.fi"),
    ],
)
def test_signature_skips_missing_parts(fields: dict[str, str], expected: str) -> None:
    signature = build_signature(_profile(**fields))
    assert signature == expected
    assert "\n\n" not in signature and not re.search(r"^ ?·|· ?$", signature, re.MULTILINE)


def test_display_website() -> None:
    assert display_website("https://palinweb.fi/") == "palinweb.fi"
    assert display_website("HTTP://palin.fi/portfolio") == "palin.fi/portfolio"
    assert display_website("palin.fi") == "palin.fi"
    assert display_website(None) is None and display_website("https://") is None


# --- Kappale 2: mitä asiakkaalle tapahtuu nyt ---

@pytest.mark.parametrize(
    ("status", "issue", "expected"),
    [
        ("NO WEBSITE", None, "kartalta, mutta ei näe palveluitanne"),
        ("NO WEBSITE", "social media only", "vain Facebookin kautta"),
        ("BROKEN WEBSITE", "DNS not resolving", "sivu ei aukea lainkaan"),
        ("BROKEN WEBSITE", "connection refused", "sivu ei aukea lainkaan"),
        ("BROKEN WEBSITE", "HTTP 500", "virheilmoituksen"),
        ("BROKEN WEBSITE", "HTTP 404", "sivua ei löydy"),
        ("BROKEN WEBSITE", "parked domain", "ei ole teidän tietojanne"),
        ("BROKEN WEBSITE", None, '"Verkkosivusto"-linkkiä, sivu ei aukea'),
        ("INSECURE", "SSL certificate expired", "selain näyttää ensin varoituksen"),
        ("INSECURE", "no HTTPS", '"ei turvallinen"'),
        ("INSECURE", None, "selain varoittaa"),
        ("NOT MOBILE", "no viewport meta", "pitää suurentaa sormilla"),
    ],
)
def test_customer_impact_is_concrete(status: str, issue: Optional[str], expected: str) -> None:
    impact = customer_impact(status, issue)
    assert expected in impact
    assert "moni" not in impact.lower() or status == "INSECURE"  # ei geneeristä "moni etsii netistä"


@pytest.mark.parametrize("status", ["UNKNOWN", "WEBSITE OK", None])
def test_no_problem_claimed_without_verified_issue(status: Optional[str]) -> None:
    assert customer_impact(status, "HTTP 403") == CUSTOMER_IMPACT_DEFAULT


def test_subject_is_personal_not_corporate() -> None:
    assert demo_email_subject(_lead("NO WEBSITE")) == "Tein teille luonnoksen nettisivuista"
    for status in ("BROKEN WEBSITE", "INSECURE", "NOT MOBILE"):
        assert demo_email_subject(_lead(status)) == "Tein teille luonnoksen uusista nettisivuista"


# --- Rakenne ---

def test_body_structure_and_order() -> None:
    body = build_demo_email_body(MODEL_TEXT, _profile(brand_name="Palin Web", website="https://palinweb.fi", phone="040 123 4567"), URL)
    head, _, tail = body.partition("\n\nTerveisin,\n")
    paragraphs = head.split("\n\n")
    assert paragraphs[0] == "Hei,"
    assert paragraphs[1].startswith("Olen Palin")  # 1: kuka olen + miten löysin
    assert paragraphs[2].startswith("Asiakas löytää teidät kartalta")  # 2: mitä tapahtuu nyt
    assert paragraphs[3] == DEMO_LINK_PARAGRAPH.format(url=URL)  # 3: linkki omalla rivillään + puhelin
    assert f"\n{URL}\n" in paragraphs[3] and "puhelimella" in paragraphs[3]
    assert paragraphs[4] == DEMO_RISK_PARAGRAPH  # 4: ilmainen, ei sido, viimeistelen tiedoillanne ja kuvillanne
    assert "ilmainen" in paragraphs[4] and "sido teitä mihinkään" in paragraphs[4] and "kuvillanne" in paragraphs[4]
    assert paragraphs[5] == "Jos haluatte jatkaa, voitte vastata suoraan tähän viestiin tai soittaa minulle numeroon 040 123 4567."
    assert len(paragraphs) == 6
    assert tail == f"Palin\nPalin Web · palinweb.fi\n040 123 4567\n\n{OPT_OUT_LINE}"
    assert word_count(head) <= DEMO_EMAIL_MAX_WORDS


def test_next_step_without_phone_only_asks_to_reply() -> None:
    body = build_demo_email_body(MODEL_TEXT, _profile(), URL)
    assert "Jos haluatte jatkaa, voitte vastata suoraan tähän viestiin.\n\nTerveisin," in body
    assert "soittaa" not in email_head(body).split("\n\n")[-1]


@pytest.mark.parametrize(
    "closing",
    [
        "Mitä pidätte luonnoksesta?",
        "Mitä mieltä olette?",
        "Kiinnostaisiko?",
        "Mitä pidätte ajatuksesta?",
        "Voisiko tämä olla teille hyödyllinen?",
    ],
)
def test_closing_opinion_question_never_ends_up_in_email(closing: str) -> None:
    body = build_demo_email_body(f"{MODEL_TEXT} {closing}\n\n{closing}", _profile(phone="040 1"), URL)
    head = email_head(body)
    assert closing not in body
    assert "?" not in head
    assert head.endswith("soittaa minulle numeroon 040 1.")


def test_model_extras_are_removed() -> None:
    text = (
        "Hei Taina,\n\n"
        "Olen Palin ja teen nettisivuja. Löysin teidät Googlesta.\n\n"
        "Asiakas ei näe aukioloaikojanne. Tein teille jo luonnoksen: https://keksitty.example [DEMO_LINKKI]\n\n"
        "Voin tehdä teille ilmaisen luonnoksen.\n\n"
        "Ystävällisin terveisin,\nPalin"
    )
    paragraphs = clean_demo_paragraphs(text)
    assert paragraphs == ["Olen Palin ja teen nettisivuja. Löysin teidät Googlesta.", "Asiakas ei näe aukioloaikojanne."]
    body = build_demo_email_body(text, _profile(), URL)
    assert "keksitty" not in body and "[DEMO_LINKKI]" not in body and "Hei Taina" not in body
    assert body.count("luonnoksen") == 1 and body.count(URL) == 1
    assert body.count("Terveisin,") == 1 and "Ystävällisin" not in body


def test_markdown_and_extra_paragraphs_are_trimmed() -> None:
    text = "**Olen Palin.**\n\n# Havainto\nAsiakas ei näe sivuanne.\n\nKolmas kappale jota ei kuulu olla."
    assert clean_demo_paragraphs(text) == ["Olen Palin.", "Havainto Asiakas ei näe sivuanne."]
    assert len(clean_demo_paragraphs("Yksi.\n\nKaksi.\n\nKolme.\n\nNeljä.")) == 2


# --- Endpoint (julkaistu demo, fake R2, fake OpenAI) ---

@pytest.fixture
def published(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    store = FakeStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: store)

    def _make(status: str, issue: Optional[str] = None) -> dict[str, Any]:
        fake_openai.reply = json.dumps(VALID)
        lead = make_lead(name="Parturi-Kampaamo Taina Lantiainen", city="Kauniainen", phone="050 1",
                         website_status=status, website_issue=issue, primary_type="hair_salon",
                         website=None if status == "NO WEBSITE" else "https://taina.example")
        client_a.post(f"/leads/{lead['id']}/demo", json={})
        demo = client_a.post(f"/leads/{lead['id']}/demo/publish").json()
        return {"lead": lead, "demo": demo}

    return _make


@pytest.mark.parametrize(
    ("status", "issue", "hint", "subject"),
    [
        ("NO WEBSITE", None, "kartalta, mutta ei näe palveluitanne", "Tein teille luonnoksen nettisivuista"),
        ("BROKEN WEBSITE", "DNS not resolving", "sivu ei aukea lainkaan", "Tein teille luonnoksen uusista nettisivuista"),
        ("INSECURE", "SSL certificate expired", "selain näyttää ensin varoituksen", "Tein teille luonnoksen uusista nettisivuista"),
    ],
)
def test_generate_email_with_demo_per_problem_type(
    client_a: TestClient, published: Any, fake_openai: type[FakeOpenAI], monkeypatch: pytest.MonkeyPatch,
    status: str, issue: Optional[str], hint: str, subject: str,
) -> None:
    monkeypatch.setattr("app.main.scrape_website_text", lambda _url: None)
    made = published(status, issue)
    fake_openai.reply = MODEL_TEXT + "\n\nMitä pidätte?"
    res = client_a.post(f"/leads/{made['lead']['id']}/generate-email", json={"require_demo_link": True})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["subject"] == subject
    prompt = fake_openai.calls[-1]["messages"]
    assert "KAKSI lyhyttä kappaletta" in prompt[0]["content"]
    assert f"ASIAKKAAN TILANNE NYT (kappale 2): " in prompt[1]["content"] and hint in prompt[1]["content"]
    body = data["body"]
    assert f"\n{made['demo']['public_url']}\n" in body
    assert "Mitä pidätte" not in body and "?" not in email_head(body)
    assert word_count(email_head(body)) <= DEMO_EMAIL_MAX_WORDS


def test_email_without_demo_keeps_previous_flow(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead = make_lead(name="Kahvila Testi", city="Espoo", website_status="NO WEBSITE")
    fake_openai.reply = "Hei,\n\nOlen Palin. Voin tehdä teille ilmaisen luonnoksen.\n\nKiinnostaisiko?"
    data = client_a.post(f"/leads/{lead['id']}/generate-email", json={}).json()
    assert data["subject"] == "Kysymys nettisivuista"
    assert "KAKSI lyhyttä kappaletta" not in fake_openai.calls[-1]["messages"][0]["content"]
    assert "Kiinnostaisiko?" in data["body"]


# --- Lähettäjäprofiilin brand_name ---

def test_sender_profile_brand_name_roundtrip(client_a: TestClient, sender_profile: dict[str, Any]) -> None:
    assert sender_profile["brand_name"] is None
    res = client_a.put("/sender-profile", json={**sender_profile, "brand_name": "  Palin Web  "})
    assert res.status_code == 200 and res.json()["brand_name"] == "Palin Web"
    assert client_a.get("/sender-profile").json()["brand_name"] == "Palin Web"
    cleared = client_a.put("/sender-profile", json={**sender_profile, "brand_name": "   "}).json()
    assert cleared["brand_name"] is None
    assert client_a.put("/sender-profile", json={**sender_profile, "brand_name": "x" * 61}).status_code == 422


def test_demo_email_mentions_existing_booking() -> None:
    body = build_demo_email_body(MODEL_TEXT, _profile(), URL, has_booking=True)
    assert "Nykyinen ajanvarauksenne toimii sivulla sellaisenaan." in email_head(body)
    assert word_count(email_head(body)) <= DEMO_EMAIL_MAX_WORDS
    assert "ajanvaraus" not in build_demo_email_body(MODEL_TEXT, _profile(), URL).lower()
