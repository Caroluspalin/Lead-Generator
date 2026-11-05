"""Demosivugeneraattori: skeema, kielletyt sisällöt, renderöinti, endpointit, tenant-isolaatio, sähköpostilinkki."""
import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.demo_site import (
    PLACE_DETAILS_FIELD_MASK,
    TEMPLATES,
    DemoAIContent,
    DemoBusiness,
    DemoSender,
    DemoStoredContent,
    content_violations,
    extract_json_object,
    fetch_opening_hours,
    new_public_token,
    parse_ai_content,
    phone_to_tel,
    render_demo_html,
    template_for_primary_type,
    validate_template_choice,
)
from tests.conftest import FakeOpenAI

VALID: dict[str, Any] = {
    "hero_title": "Parturi-kampaamo Kauniaisissa",
    "hero_subtitle": "Hiustenleikkaukset, värjäykset ja kampaukset koko perheelle.",
    "about": "Olemme paikallinen parturi-kampaamo. Tarjoamme hiustenhoitoa naisille, miehille ja lapsille. Varatkaa aika puhelimitse.",
    "services": [
        {"name": "Hiustenleikkaus", "description": "Leikkaus toiveidenne mukaan, myös lapsille."},
        {"name": "Värjäys", "description": "Kestovärit, raidat ja sävytykset hiuksillenne sopivasti."},
        {"name": "Kampaukset", "description": "Juhlakampaukset ja kampaukset erityisiin tilaisuuksiin."},
    ],
}
ALLOWED = "Parturi-Kampaamo Taina Lantiainen Kauniainen"


def _content(**overrides: Any) -> DemoAIContent:
    return DemoAIContent.model_validate({**VALID, **overrides})


# --- Skeema ---

def test_valid_content_passes_schema_and_rules() -> None:
    assert content_violations(_content(), allowed_text=ALLOWED) == []


@pytest.mark.parametrize(
    "bad",
    [
        {"services": VALID["services"][:2]},  # liian vähän
        {"services": VALID["services"] * 3},  # liian monta (9)
        {"hero_title": "Hei"},  # liian lyhyt
        {"about": "x" * 701},
        {"extra_field": "ei sallittu"},
    ],
)
def test_schema_rejects_invalid(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DemoAIContent.model_validate({**VALID, **bad})


def test_schema_rejects_extra_service_fields() -> None:
    services = [{**VALID["services"][0], "price": "30 €"}] + VALID["services"][1:]
    with pytest.raises(ValidationError):
        DemoAIContent.model_validate({**VALID, "services": services})


def test_ai_schema_has_no_price_or_contact_fields() -> None:
    assert set(DemoAIContent.model_fields) == {"hero_title", "hero_subtitle", "about", "services"}


# --- Kielletyt sisällöt ---

@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("about", "Hiustenleikkaus alkaen kolmekymmentä euroa. Tervetuloa käymään meillä paikan päällä.", "hinnat"),
        ("about", "Leikkaus maksaa vain 25 €. Tervetuloa käymään meillä paikan päällä ja nauttimaan.", "numeroita"),
        ("about", "Olemme palvelleet asiakkaita vuodesta 1998 lähtien. Tervetuloa käymään meillä paikan päällä.", "numeroita"),
        ("about", "Asiakkaamme sanovat: ”Paras parturi koko kaupungissa.” Tervetuloa käymään meillä.", "lainausmerkkejä"),
        ("about", "Meillä on erinomaiset arvostelut ja viiden tähden palvelu. Tervetuloa käymään meillä.", "arvostelut"),
        ("about", "Olemme palkittu alan kilpailussa ja ylpeitä siitä. Tervetuloa käymään meillä paikan päällä.", "palkinnot"),
        ("about", "Yritys on perustettu kauan sitten ja palvelee yhä. Tervetuloa käymään meillä paikan päällä.", "historia"),
        ("about", "Tyytyväiset asiakkaat palaavat aina uudelleen luoksemme. Tervetuloa käymään meillä paikan päällä.", "asiakaskehut"),
        ("about", "Kampaajamme Maija ja Liisa palvelevat teitä mielellään. Tervetuloa käymään meillä paikan päällä.", "keksitty nimi 'Maija'"),
        ("hero_subtitle", "Upea ja ainutlaatuinen kampaamo teille.", "kielletty sana 'upea'"),
    ],
)
def test_invented_content_is_rejected(field: str, value: str, expected: str) -> None:
    problems = content_violations(_content(**{field: value}), allowed_text=ALLOWED)
    assert any(expected in p for p in problems), problems


def test_names_from_business_or_site_are_allowed() -> None:
    about = "Tainan kampaamo palvelee Kauniaisissa. Käytämme Kevin Murphy -tuotteita. Tervetuloa käymään meillä."
    assert content_violations(_content(about=about), allowed_text=ALLOWED + " Kevin Murphy hiustuotteet") == []


def test_parse_ai_content_handles_code_fence_and_garbage() -> None:
    content, problems = parse_ai_content("```json\n" + json.dumps(VALID) + "\n```", allowed_text=ALLOWED)
    assert content is not None and problems == []
    content, problems = parse_ai_content("en osaa", allowed_text=ALLOWED)
    assert content is None and "skeemavirhe" in problems[0]


def test_extract_json_object() -> None:
    assert extract_json_object('Tässä: {"a": 1} kiitos') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json_object("[1, 2]")


# --- Pohjat ---

@pytest.mark.parametrize(
    ("primary_type", "template"),
    [
        ("hair_salon", "beauty"), ("barber_shop", "beauty"), ("beauty_salon", "beauty"), ("nail_salon", "beauty"),
        ("restaurant", "restaurant"), ("cafe", "restaurant"), ("coffee_shop", "restaurant"), ("pizza_restaurant", "restaurant"),
        ("plumber", "services"), ("car_repair", "services"), (None, "services"),
    ],
)
def test_template_for_primary_type(primary_type: str | None, template: str) -> None:
    assert template_for_primary_type(primary_type) == template


def test_each_template_has_two_to_three_schemes() -> None:
    assert set(TEMPLATES) == {"beauty", "restaurant", "services"}
    for t in TEMPLATES.values():
        assert 2 <= len(t.schemes) <= 3


def test_validate_template_choice() -> None:
    assert validate_template_choice("beauty", None) == ("beauty", "rose")
    assert validate_template_choice("restaurant", "rose") == ("restaurant", "terracotta")  # väri ei kuulu pohjaan
    with pytest.raises(ValueError):
        validate_template_choice("wordpress", None)


@pytest.mark.parametrize(
    ("phone", "tel"),
    [("09 5052970", "+35895052970"), ("040 123 4567", "+358401234567"), ("+358 40 1", "+358401"), (None, None), ("", None)],
)
def test_phone_to_tel(phone: str | None, tel: str | None) -> None:
    assert phone_to_tel(phone) == tel


# --- Renderöinti ---

BUSINESS = DemoBusiness(
    name="Parturi-Kampaamo Taina Lantiainen", city="Kauniainen", address="Kauniaistentie 7, 02700 Kauniainen",
    phone="09 505 2970", maps_url="https://maps.google.com/?cid=1",
)
SENDER = DemoSender(name="Palin", company_name=None, phone="040 123 4567", website="https://palin.fi")


def _render(template: str = "beauty", scheme: str = "rose", **content: Any) -> str:
    stored = DemoStoredContent.model_validate({**VALID, **content})
    return render_demo_html(template=template, color_scheme=scheme, content=stored, business=BUSINESS, sender=SENDER)


@pytest.mark.parametrize("template", ["beauty", "restaurant", "services"])
def test_render_always_has_banner_noindex_and_no_script(template: str) -> None:
    for scheme in TEMPLATES[template].schemes:
        html = _render(template, scheme)
        assert '<meta name="robots" content="noindex, nofollow">' in html
        assert "Tämä on luonnos, jonka Palin teki yritykselle Parturi-Kampaamo Taina Lantiainen. Ei yrityksen virallinen sivu." in html
        assert "040 123 4567" in html and "https://palin.fi" in html
        assert "<script" not in html.lower()
        assert "<img" not in html.lower()
        assert not re.search(r'src="https?://', html)
        assert '<html lang="fi">' in html


def test_render_sections_and_links() -> None:
    html = _render(opening_hours=["maanantai: 9.00–17.00", "sunnuntai: Suljettu"])
    assert 'href="tel:+35895052970"' in html
    assert 'href="https://maps.google.com/?cid=1"' in html
    for anchor in ('id="palvelut"', 'id="tietoa"', 'id="aukioloajat"', 'id="yhteystiedot"', "<footer"):
        assert anchor in html
    assert "Maanantai" in html and "9.00–17.00" in html
    assert "Hinnat ja ajanvaraus puhelimitse." in html
    assert 'viewport' in html


def test_render_without_hours_asks_to_call() -> None:
    assert "Kysykää aukioloajat puhelimitse." in _render()


def test_render_escapes_user_text() -> None:
    html = _render(about="<script>alert(1)</script> Tervetuloa käymään meillä paikan päällä ja nauttimaan.")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# --- Token ---

def test_public_token_is_long_and_unpredictable() -> None:
    tokens = {new_public_token() for _ in range(500)}
    assert len(tokens) == 500
    assert all(len(t) >= 43 and re.fullmatch(r"[A-Za-z0-9_-]+", t) for t in tokens)


# --- Place Details ---

def test_fetch_opening_hours_field_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class _R:
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict[str, Any]:
            return {"regularOpeningHours": {"weekdayDescriptions": ["maanantai: 9.00–17.00"]}}

    def _get(url: str, **kwargs: Any) -> _R:
        calls.append({"url": url, **kwargs})
        return _R()

    monkeypatch.setattr("requests.get", _get)
    assert fetch_opening_hours("ChIJabc", "AIza-x") == ["maanantai: 9.00–17.00"]
    assert calls[0]["url"] == "https://places.googleapis.com/v1/places/ChIJabc"
    assert calls[0]["headers"] == {"X-Goog-Api-Key": "AIza-x", "X-Goog-FieldMask": "regularOpeningHours"}
    assert PLACE_DETAILS_FIELD_MASK == "regularOpeningHours"
    assert calls[0]["params"] == {"languageCode": "fi"}


def test_fetch_opening_hours_error_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    class _R:
        status_code = 403
        text = "PERMISSION_DENIED"

    monkeypatch.setattr("requests.get", lambda *a, **k: _R())
    assert fetch_opening_hours("ChIJabc", "AIza-x") is None


# --- Endpointit ---

@pytest.fixture
def demo_ready(fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]) -> type[FakeOpenAI]:
    fake_openai.reply = json.dumps(VALID)
    return fake_openai


@pytest.fixture
def lead(make_lead: Any) -> dict[str, Any]:
    return make_lead(
        name="Parturi-Kampaamo Taina Lantiainen", city="Kauniainen", address="Kauniaistentie 7",
        phone="09 505 2970", website_status="NO WEBSITE", primary_type="hair_salon",
        google_place_id="ChIJtaina", maps_url="https://maps.google.com/?cid=1",
    )


def test_generate_demo(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    res = client_a.post(f"/leads/{lead['id']}/demo", json={})
    assert res.status_code == 200, res.text
    demo = res.json()
    assert demo["template"] == "beauty" and demo["color_scheme"] == "rose"
    assert demo["status"] == "draft"
    assert demo["content"]["hero_title"] == VALID["hero_title"]
    assert demo["content"]["price_note"] == "Hinnat ja ajanvaraus puhelimitse."
    assert demo["preview_url"] == f"http://127.0.0.1:8000/demo/{demo['public_token']}"
    assert "html" not in demo
    assert len(demo_ready.calls) == 1
    assert "Palauta VAIN yksi JSON-objekti" in demo_ready.calls[0]["messages"][0]["content"]

    page = client_a.get(f"/demo/{demo['public_token']}")
    assert page.status_code == 200
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    assert "script-src" not in page.headers["content-security-policy"]
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert '<meta name="robots" content="noindex, nofollow">' in page.text
    assert "Tämä on luonnos, jonka Palin teki" in page.text


def test_demo_does_not_call_place_details_in_mock_mode(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]
) -> None:
    # conftest estää requests.get:n: jos Place Detailsia kutsuttaisiin, generointi kaatuisi verkkoestoon
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert demo["content"]["opening_hours"] == []


def test_demo_fetches_hours_in_live_mode(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.USE_LIVE_GOOGLE", True)
    monkeypatch.setattr("app.main.GOOGLE_API_KEY", "AIza-test")
    seen: list[str] = []
    monkeypatch.setattr("app.main.fetch_opening_hours", lambda pid, key: seen.append(pid) or ["maanantai: 9.00–17.00"])
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert seen == ["ChIJtaina"]
    assert demo["content"]["opening_hours"] == ["maanantai: 9.00–17.00"]


def test_invalid_ai_content_retried_once(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    bad = {**VALID, "about": "Leikkaus vain 25 €! Asiakkaamme sanovat: ”paras”. Tervetuloa käymään meillä."}
    demo_ready.replies = [json.dumps(bad), json.dumps(VALID)]
    res = client_a.post(f"/leads/{lead['id']}/demo", json={})
    assert res.status_code == 200
    assert len(demo_ready.calls) == 2
    retry_prompt_text = demo_ready.calls[1]["messages"][1]["content"]
    assert "EDELLINEN VASTAUS HYLÄTTIIN" in retry_prompt_text and "numeroita" in retry_prompt_text


def test_invalid_ai_content_twice_is_502(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    demo_ready.replies = ["ei jsonia", json.dumps({**VALID, "services": []})]
    res = client_a.post(f"/leads/{lead['id']}/demo", json={})
    assert res.status_code == 502
    assert len(demo_ready.calls) == 2
    assert client_a.get(f"/leads/{lead['id']}/demo").status_code == 404


def test_generate_demo_requires_profile(client_a: TestClient, lead: dict[str, Any], fake_openai: type[FakeOpenAI]) -> None:
    assert client_a.post(f"/leads/{lead['id']}/demo", json={}).status_code == 428
    assert fake_openai.calls == []


def test_generate_demo_blocked_for_do_not_contact(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]
) -> None:
    client_a.patch(f"/leads/{lead['id']}", json={"do_not_contact": True})
    assert client_a.post(f"/leads/{lead['id']}/demo", json={}).status_code == 409


def test_regenerate_keeps_token(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    first = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    second = client_a.post(f"/leads/{lead['id']}/demo", json={"template": "services"}).json()
    assert second["id"] == first["id"]
    assert second["public_token"] == first["public_token"]
    assert second["template"] == "services"


def test_patch_rerenders_without_ai_call(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    calls_before = len(demo_ready.calls)
    edited = {k: v for k, v in demo["content"].items() if k != "opening_hours"}
    edited["hero_title"] = "Tainan kampaamo"
    edited["price_note"] = "Hiustenleikkaus alkaen 30 €, varaukset puhelimitse."  # käyttäjä saa kirjoittaa oikean hinnan
    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "services", "color_scheme": "forest", "content": edited})
    assert res.status_code == 200, res.text
    assert len(demo_ready.calls) == calls_before
    updated = res.json()
    assert (updated["template"], updated["color_scheme"]) == ("services", "forest")
    page = client_a.get(f"/demo/{demo['public_token']}").text
    assert "Tainan kampaamo" in page and "alkaen 30 €" in page and "#2f6a3f" in page


def test_patch_template_only_resets_incompatible_scheme(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]
) -> None:
    client_a.post(f"/leads/{lead['id']}/demo", json={})
    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "restaurant"}).json()
    assert (res["template"], res["color_scheme"]) == ("restaurant", "terracotta")


def test_patch_rejects_invalid_content(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    bad = {**{k: v for k, v in demo["content"].items() if k != "opening_hours"}, "services": []}
    assert client_a.patch(f"/leads/{lead['id']}/demo", json={"content": bad}).status_code == 422
    assert client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "nope"}).status_code == 422


def test_delete_demo_and_public_link(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert client_a.delete(f"/leads/{lead['id']}/demo").json() == {"ok": True}
    assert client_a.get(f"/demo/{demo['public_token']}").status_code == 404
    assert client_a.get(f"/leads/{lead['id']}/demo").status_code == 404


def test_deleting_lead_deletes_demo(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    client_a.delete(f"/leads/{lead['id']}")
    assert client_a.get(f"/demo/{demo['public_token']}").status_code == 404


def test_expired_demo_is_410(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI], session: Any) -> None:
    from app.models import Demo
    from sqlmodel import select
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    row = session.exec(select(Demo)).one()
    row.status = "expired"
    session.add(row)
    session.commit()
    assert client_a.get(f"/demo/{demo['public_token']}").status_code == 410


def test_unknown_token_is_404(client_a: TestClient) -> None:
    res = client_a.get(f"/demo/{new_public_token()}")
    assert res.status_code == 404
    assert res.headers["x-robots-tag"] == "noindex, nofollow"


def test_templates_catalog_endpoint(client_a: TestClient) -> None:
    catalog = client_a.get("/demo-templates").json()
    assert [t["id"] for t in catalog] == ["beauty", "restaurant", "services"]
    assert {s["id"] for s in catalog[0]["color_schemes"]} == {"rose", "sage", "noir"}


# --- Tenant-isolaatio ---

def test_other_user_cannot_access_demo(
    client_a: TestClient, client_b: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]
) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert client_b.get(f"/leads/{lead['id']}/demo").status_code == 404
    assert client_b.patch(f"/leads/{lead['id']}/demo", json={"template": "services"}).status_code == 404
    assert client_b.delete(f"/leads/{lead['id']}/demo").status_code == 404
    assert client_b.post(f"/leads/{lead['id']}/demo", json={}).status_code == 404
    assert client_a.get(f"/leads/{lead['id']}/demo").json()["template"] == demo["template"]


# --- Sähköposti ---

def test_email_includes_demo_link_only_when_demo_exists(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]
) -> None:
    demo_ready.reply = "Hei,\n\nEn löytänyt teille nettisivua.\n\nVoin tehdä teille ilmaisen luonnoksen."
    without = client_a.post(f"/leads/{lead['id']}/generate-email", json={}).json()["body"]
    assert "/demo/" not in without
    assert "TARJOUS: Voin tehdä teille ilmaisen luonnoksen" in demo_ready.calls[-1]["messages"][1]["content"]

    demo_ready.reply = json.dumps(VALID)
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()

    demo_ready.reply = "Hei,\n\nTein teille valmiin luonnoksen, voitte katsoa sen täältä: [DEMO_LINKKI]\n\nKiinnostaisiko?"
    with_demo = client_a.post(f"/leads/{lead['id']}/generate-email", json={}).json()["body"]
    assert f"voitte katsoa sen täältä: {demo['preview_url']}" in with_demo
    assert "[DEMO_LINKKI]" not in with_demo
    assert f"TARJOUS: Tein teille valmiin luonnoksen, voitte katsoa sen täältä: [DEMO_LINKKI]" in demo_ready.calls[-1]["messages"][1]["content"]

    client_a.delete(f"/leads/{lead['id']}/demo")
    demo_ready.reply = "Hei,\n\nTein luonnoksen: [DEMO_LINKKI]"
    after_delete = client_a.post(f"/leads/{lead['id']}/generate-email", json={}).json()["body"]
    assert "/demo/" not in after_delete and "[DEMO_LINKKI]" not in after_delete


def test_email_demo_link_added_by_code_if_model_drops_placeholder(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]
) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    demo_ready.reply = "Hei,\n\nTein teille luonnoksen, katsokaa: https://keksitty.example/abc\n\nKiinnostaisiko?"
    body = client_a.post(f"/leads/{lead['id']}/generate-email", json={}).json()["body"]
    assert "keksitty.example" not in body
    assert f"Luonnos: {demo['preview_url']}" in body
