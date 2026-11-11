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
    OpeningHours,
    OpeningPeriod,
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
    "hero_title": "Hiukset kuntoon Kauniaisissa",
    "hero_subtitle": "Leikkaukset, värit ja kampaukset koko perheelle.",
    "about": "Olemme paikallinen liike. Leikkaamme naisten, miesten ja lasten hiukset.",
    "services": [
        {"name": "Hiustenleikkaus", "description": "Leikkaus toiveidenne mukaan, myös lapsille."},
        {"name": "Värjäys", "description": "Kestovärit, raidat ja sävytykset."},
        {"name": "Kampaukset", "description": "Juhlakampaukset häihin ja muihin tilaisuuksiin."},
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
    assert set(DemoAIContent.model_fields) == {"hero_title", "hero_subtitle", "about_title", "about", "services"}


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
        ("hair_salon", "salon"), ("barber_shop", "barber"), ("beauty_salon", "salon"), ("nail_salon", "salon"),
        ("restaurant", "restaurant"), ("cafe", "cafe"), ("coffee_shop", "cafe"), ("bakery", "cafe"), ("tea_house", "cafe"),
        ("steak_house", "restaurant"), ("pizza_restaurant", "restaurant"),
        ("plumber", "services"), ("car_repair", "services"), (None, "services"),
    ],
)
def test_template_for_primary_type(primary_type: str | None, template: str) -> None:
    assert template_for_primary_type(primary_type) == template


def test_each_template_has_two_to_three_schemes() -> None:
    assert set(TEMPLATES) == {"cafe", "salon", "barber", "premium", "beauty", "restaurant", "services"}
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
        # Ilman Unsplash-kuvia ei yhtään ulkoista resurssia
        assert "<img" not in html.lower()
        assert not re.search(r'src="https?://', html)
        assert "font-family:'" in html and "data:font/woff2;base64," in html
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
            return {"regularOpeningHours": {
                "weekdayDescriptions": ["maanantai: 9.00–17.00"],
                "periods": [{"open": {"day": 1, "hour": 9, "minute": 0}, "close": {"day": 1, "hour": 17, "minute": 0}}],
            }}

    def _get(url: str, **kwargs: Any) -> _R:
        calls.append({"url": url, **kwargs})
        return _R()

    monkeypatch.setattr("requests.get", _get)
    assert fetch_opening_hours("ChIJabc", "AIza-x") == OpeningHours(
        descriptions=["maanantai: 9.00–17.00"], periods=[OpeningPeriod(day=1, open="09:00", close="17:00")]
    )
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
    res = client_a.post(f"/leads/{lead['id']}/demo", json={"template": "beauty"})
    assert res.status_code == 200, res.text
    demo = res.json()
    assert demo["template"] == "beauty" and demo["color_scheme"] == "rose"
    assert demo["status"] == "draft"
    assert demo["content"]["hero_title"] == VALID["hero_title"]
    assert demo["content"]["price_note"] == "Hinnat ja ajanvaraus puhelimitse."
    assert demo["preview_url"] == f"http://testserver/demo/{demo['public_path']}"
    assert demo["public_url"] is None and demo["publishing_enabled"] is False
    assert "html" not in demo
    assert len(demo_ready.calls) == 1
    assert "Palauta VAIN yksi JSON-objekti" in demo_ready.calls[0]["messages"][0]["content"]

    page = client_a.get(f"/demo/{demo['public_path']}")
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
    hours = OpeningHours(
        descriptions=["maanantai: 9.00–17.00"], periods=[OpeningPeriod(day=1, open="09:00", close="17:00")]
    )
    monkeypatch.setattr("app.main.fetch_opening_hours", lambda pid, key: seen.append(pid) or hours)
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert seen == ["ChIJtaina"]
    assert demo["content"]["opening_hours"] == ["maanantai: 9.00–17.00"]
    assert demo["content"]["opening_periods"] == [{"day": 1, "open": "09:00", "close": "17:00"}]


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
    assert second["public_path"] == first["public_path"]
    assert second["template"] == "services"


def test_patch_rerenders_without_ai_call(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    calls_before = len(demo_ready.calls)
    edited = {k: v for k, v in demo["content"].items() if k not in ("opening_hours", "opening_periods", "images", "site_based", "timma")}
    edited["hero_title"] = "Tainan kampaamo"
    edited["price_note"] = "Hiustenleikkaus alkaen 30 €, varaukset puhelimitse."  # käyttäjä saa kirjoittaa oikean hinnan
    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "services", "color_scheme": "forest", "content": edited})
    assert res.status_code == 200, res.text
    assert len(demo_ready.calls) == calls_before
    updated = res.json()
    assert (updated["template"], updated["color_scheme"]) == ("services", "forest")
    page = client_a.get(f"/demo/{demo['public_path']}").text
    assert "Tainan kampaamo" in page and "alkaen 30 €" in page and "#2f6a3f" in page


def test_patch_template_only_resets_incompatible_scheme(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]
) -> None:
    client_a.post(f"/leads/{lead['id']}/demo", json={})
    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "restaurant"}).json()
    assert (res["template"], res["color_scheme"]) == ("restaurant", "terracotta")


def test_patch_rejects_invalid_content(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    bad = {**{k: v for k, v in demo["content"].items() if k not in ("opening_hours", "opening_periods", "images", "site_based", "timma")}, "services": []}
    assert client_a.patch(f"/leads/{lead['id']}/demo", json={"content": bad}).status_code == 422
    assert client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "nope"}).status_code == 422


def test_delete_demo_and_public_link(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert client_a.delete(f"/leads/{lead['id']}/demo").json() == {"ok": True}
    assert client_a.get(f"/demo/{demo['public_path']}").status_code == 404
    assert client_a.get(f"/leads/{lead['id']}/demo").status_code == 404


def test_deleting_lead_deletes_demo(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    client_a.delete(f"/leads/{lead['id']}")
    assert client_a.get(f"/demo/{demo['public_path']}").status_code == 404


def test_expired_demo_is_410(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI], session: Any) -> None:
    from app.models import Demo
    from sqlmodel import select
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    row = session.exec(select(Demo)).one()
    row.status = "expired"
    session.add(row)
    session.commit()
    assert client_a.get(f"/demo/{demo['public_path']}").status_code == 410


def test_unknown_token_is_404(client_a: TestClient) -> None:
    res = client_a.get(f"/demo/{new_public_token()}")
    assert res.status_code == 404
    assert res.headers["x-robots-tag"] == "noindex, nofollow"


def test_templates_catalog_endpoint(client_a: TestClient) -> None:
    catalog = client_a.get("/demo-templates").json()
    # Uudet (versio 2) pohjat ensin
    assert [t["id"] for t in catalog] == ["cafe", "salon", "barber", "premium", "beauty", "restaurant", "services"]
    assert {s["id"] for s in catalog[0]["color_schemes"]} == {"paahto", "kaura", "ruis"}
    assert {s["id"] for s in catalog[4]["color_schemes"]} == {"rose", "sage", "noir"}


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



# --- Kuvat (Unsplash) ---

from app.demo_icons import ICONS, service_icon_names  # noqa: E402
from app.demo_site import TEMPLATE_FONTS, DemoImages, font_face_css  # noqa: E402
from app.utils import unsplash  # noqa: E402
from app.utils.unsplash import DemoPhoto  # noqa: E402


def _api_photo(pid: str, alt: str = "empty salon chairs", **user: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "alt_description": alt,
        "description": None,
        "urls": {"raw": f"https://images.unsplash.com/photo-{pid}?ixid=abc{pid}", "regular": "x"},
        "links": {"download_location": f"https://api.unsplash.com/photos/{pid}/download?ixid=abc{pid}"},
        "user": {"name": user.get("name", f"Kuvaaja {pid}"), "username": f"u{pid}", "links": {"html": f"https://unsplash.com/@u{pid}"}},
    }


class _UnsplashFake:
    def __init__(self, pages: dict[str, list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        query = (kwargs.get("params") or {}).get("query")
        data = {"results": self.pages.get(query, [])} if url.endswith("/search/photos") else {}

        class _R:
            status_code = 200
            headers = {"X-Ratelimit-Remaining": "49"}
            text = ""

            @staticmethod
            def json() -> dict[str, Any]:
                return data

        return _R()


def _photo(pid: str, people: bool = False) -> DemoPhoto:
    return DemoPhoto(
        id=pid, raw_url=f"https://images.unsplash.com/photo-{pid}?ixid=x{pid}", alt="", photographer_name=f"Kuvaaja {pid}",
        photographer_url=f"https://unsplash.com/@u{pid}", download_location=f"https://api.unsplash.com/photos/{pid}/download",
        has_people=people,
    )


def test_search_photos_request_and_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _UnsplashFake({"hair salon interior": [_api_photo("a"), _api_photo("b", alt="woman getting a haircut")]})
    monkeypatch.setattr("requests.get", fake)
    photos = unsplash.search_photos("hair salon interior", "key-123")
    call = fake.calls[0]
    assert call["url"] == "https://api.unsplash.com/search/photos"
    assert call["headers"] == {"Authorization": "Client-ID key-123", "Accept-Version": "v1"}
    assert call["params"] == {"query": "hair salon interior", "per_page": 20, "orientation": "landscape", "content_filter": "high"}
    assert [p.id for p in photos] == ["a", "b"]
    assert photos[0].has_people is False and photos[1].has_people is True
    assert photos[0].photographer_url == "https://unsplash.com/@ua"


def test_search_photos_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    class _R:
        status_code = 403
        text = "Rate Limit Exceeded"
        headers: dict[str, str] = {}

    monkeypatch.setattr("requests.get", lambda *a, **k: _R())
    assert unsplash.search_photos("x", "key") == []


@pytest.mark.parametrize(
    ("primary_type", "template", "first_query"),
    [
        ("hair_salon", "beauty", "hair salon interior"),
        ("barber_shop", "beauty", "barbershop interior"),
        ("hair_care", "beauty", "hair salon interior"),  # ei "car workshop"
        ("cafe", "restaurant", "cafe interior"),
        ("car_repair", "services", "car workshop"),
        (None, "beauty", "beauty salon interior"),
    ],
)
def test_image_queries_by_industry_not_business_name(primary_type: str | None, template: str, first_query: str) -> None:
    assert unsplash.image_queries(primary_type, template)[0] == first_query


def test_second_query_only_when_first_is_thin(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _UnsplashFake({"hair salon interior": [_api_photo("a")], "hairdresser tools": [_api_photo(c) for c in "bcde"]})
    monkeypatch.setattr("requests.get", fake)
    assert len(unsplash.find_candidates("hair_salon", "beauty", "k")) == 5
    assert len(fake.calls) == 2

    fake = _UnsplashFake({"hair salon interior": [_api_photo(c) for c in "abcdef"]})
    monkeypatch.setattr("requests.get", fake)
    unsplash.find_candidates("hair_salon", "beauty", "k")
    assert len(fake.calls) == 1


def test_choose_images_prefers_hero_without_people() -> None:
    hero, mood, options = unsplash.choose_images([_photo("p1", people=True), _photo("a"), _photo("b"), _photo("c"), _photo("d")])
    assert hero is not None and hero.id == "a"
    assert [m.id for m in mood] == ["b", "c", "d"]  # ihmiskuvat vaihtoehtolistan loppuun
    assert options[0].id == "a" and len(options) == 5


def test_photo_url_keeps_ixid_and_adds_params() -> None:
    url = unsplash.photo_url(_photo("a"), 1080)
    assert url.startswith("https://images.unsplash.com/photo-a?ixid=xa&")
    assert "w=1080" in url and "auto=format" in url and "fit=crop" in url


def test_attribution_links_have_utm() -> None:
    assert unsplash.with_utm("https://unsplash.com/@ua", "agency_hunter") == "https://unsplash.com/@ua?utm_source=agency_hunter&utm_medium=referral"
    assert unsplash.unsplash_home_url("agency_hunter") == "https://unsplash.com/?utm_source=agency_hunter&utm_medium=referral"


def test_render_with_images_has_attribution_and_srcset() -> None:
    images = DemoImages(hero=_photo("h"), mood=[_photo("m1"), _photo("m2")], options=[_photo("h"), _photo("m1"), _photo("m2")])
    html = _render(images=images.model_dump())
    assert 'src="https://images.unsplash.com/photo-h?ixid=xh&amp;w=1600' in html or "photo-h?ixid=xh&amp;w=" in html
    assert "srcset=" in html
    assert html.count("/ <a href=\"https://unsplash.com/?utm_source=agency_hunter&amp;utm_medium=referral\"") == 3
    assert 'href="https://unsplash.com/@uh?utm_source=agency_hunter&amp;utm_medium=referral"' in html
    assert "Kuva: <a" in html and ">Kuvaaja h</a>" in html
    assert 'class="gallery n2"' in html
    # Vain Unsplashin kuvat ulkoisena resurssina
    assert set(re.findall(r'src="(https?://[^/"]+)', html)) == {"https://images.unsplash.com"}


def test_render_without_images_uses_gradient() -> None:
    html = _render()
    assert 'class="hero no-image"' in html and "hero-deco" in html
    assert "gallery" not in html.split("<main", 1)[1].split("palvelut", 1)[0]


# --- Visuaalinen ilme ---

def test_hero_shows_business_name_as_h1_and_ai_title_as_eyebrow() -> None:
    html = _render()
    assert '<h1 id="hero-title">Parturi-Kampaamo Taina Lantiainen</h1>' in html
    assert '<p class="eyebrow">Hiukset kuntoon Kauniaisissa</p>' in html


def test_banner_is_single_line_and_footer_does_not_repeat_it() -> None:
    html = _render()
    banner = "Tämä on luonnos, jonka Palin teki yritykselle Parturi-Kampaamo Taina Lantiainen. Ei yrityksen virallinen sivu."
    assert html.count(banner) == 1
    bar = html.split('<div class="demo-bar"', 1)[1].split("</div>", 1)[0]
    assert banner in bar and "040 123 4567" in bar and "palin.fi" in bar
    assert "<p" not in bar  # yksi rivi, ei kappaleita
    # Mobiilissa lyhyt versio (CSS vaihtaa .long/.short), sivusto vain leveällä näytöllä
    assert '<span class="short">Luonnos – ei virallinen sivu · Palin</span>' in bar
    assert ".demo-bar .long{display:none}" in html and ".demo-bar .short{display:none}" in html
    assert "luonnos" not in html.split('<footer', 1)[1].lower()


@pytest.mark.parametrize("template", ["beauty", "restaurant", "services"])
def test_each_template_embeds_its_own_heading_font(template: str) -> None:
    html = _render(template, next(iter(TEMPLATES[template].schemes)))
    font = TEMPLATE_FONTS[template]
    assert f"font-family:'{font.family}'" in html
    assert font_face_css(template) in html


def test_fonts_have_licenses() -> None:
    from pathlib import Path
    fonts = Path(__file__).resolve().parent.parent / "app" / "templates" / "demo" / "fonts"
    for font in TEMPLATE_FONTS.values():
        assert (fonts / font.file).stat().st_size < 40_000
    assert len(list(fonts.glob("OFL-*.txt"))) == 3


def test_service_icons_match_services_and_are_unique() -> None:
    services = [
        ("Hiustenleikkaus", "Leikkaus toiveidenne mukaan."),
        ("Hiusten värjäys", "Värjäämme hiuksia."),
        ("Hiusten muotoilu", "Muotoilemme hiukset juhlaan."),
        ("Hiustenhoito", "Hoidamme hiuksia."),
        ("Parranajo", "Autamme teitä parran kanssa."),
        ("Lasten leikkaus", "Leikkaamme lasten hiukset."),
    ]
    icons = service_icon_names(services, "beauty")
    assert icons[:5] == ["scissors", "palette", "wind", "leaf", "razor"]
    assert len(set(icons)) == 6
    assert "car" not in icons  # "Autamme" ei ole auto


def test_service_icons_fallback_pool_for_unknown_services() -> None:
    icons = service_icon_names([("Palvelu A", "Jotain."), ("Palvelu B", "Muuta."), ("Palvelu C", "Kolmas.")], "restaurant")
    assert icons == ["utensils", "cup", "wine"]
    assert all(i in ICONS for i in icons)


@pytest.mark.parametrize("count", [3, 4, 5, 6])
def test_services_grid_class_by_count(count: int) -> None:
    services = [{"name": f"Palvelu {i}", "description": "Kuvaus palvelusta tässä."} for i in range(count)]
    html = _render(services=services)
    assert f'class="services n{count}"' in html
    assert html.count('<article class="card">') == count


def test_css_handles_odd_counts_without_lonely_card() -> None:
    html = _render()
    assert ".services.n3>:last-child,.services.n5>:last-child{grid-column:1/-1}" in html
    assert ".services.n5>:nth-child(4),.services.n5>:nth-child(5){grid-column:span 3}" in html


# --- Kuvat endpointin kautta ---

@pytest.fixture
def unsplash_ready(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    photos = [_photo("p1", people=True)] + [_photo(c) for c in "abcd"]
    monkeypatch.setattr("app.main.UNSPLASH_ACCESS_KEY", "key-123")
    monkeypatch.setattr("app.main.unsplash.find_candidates", lambda pt, tpl, key: photos)
    tracked: list[str] = []
    monkeypatch.setattr("app.main.unsplash.track_download", lambda photo, key: tracked.append(photo.id))
    return tracked


def test_generate_demo_with_images_tracks_downloads(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI], unsplash_ready: list[str]
) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={"template": "beauty"}).json()
    images = demo["content"]["images"]
    assert images["hero"]["id"] == "a"
    assert [m["id"] for m in images["mood"]] == ["b", "c", "d"]
    assert len(images["options"]) == 5
    assert unsplash_ready == ["a", "b", "c", "d"]  # hero + tunnelmakuvat
    page = client_a.get(f"/demo/{demo['public_path']}")
    assert "img-src data: https://images.unsplash.com" in page.headers["content-security-policy"]
    assert "font-src data:" in page.headers["content-security-policy"]
    assert "photo-a?ixid=xa" in page.text


def test_generate_demo_without_unsplash_key_uses_gradient(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]
) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={"template": "beauty"}).json()
    assert demo["content"]["images"] == {"hero": None, "mood": [], "options": []}
    assert 'class="hero no-image"' in client_a.get(f"/demo/{demo['public_path']}").text


def test_patch_hero_image(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI], unsplash_ready: list[str]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={"template": "beauty"}).json()
    unsplash_ready.clear()
    calls_before = len(demo_ready.calls)

    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"hero_image_id": "d"}).json()
    assert res["content"]["images"]["hero"]["id"] == "d"
    assert "d" not in [m["id"] for m in res["content"]["images"]["mood"]]
    assert unsplash_ready == []  # kaikki neljä (a-d) olivat jo käytössä, vain roolit vaihtuivat
    assert len(demo_ready.calls) == calls_before
    assert "photo-d?ixid=xd" in client_a.get(f"/demo/{demo['public_path']}").text

    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"hero_image_id": "p1"}).json()
    assert res["content"]["images"]["hero"]["id"] == "p1"
    assert unsplash_ready == ["p1"]  # ainoa uusi käyttöön otettu kuva

    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"hero_image_id": "none"}).json()
    assert res["content"]["images"]["hero"] is None
    assert client_a.patch(f"/leads/{lead['id']}/demo", json={"hero_image_id": "keksitty"}).status_code == 422


def test_text_edit_keeps_images(client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI], unsplash_ready: list[str]) -> None:
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    edited = {k: v for k, v in demo["content"].items() if k not in ("opening_hours", "opening_periods", "images", "site_based", "timma")}
    edited["about"] = "Muokattu esittelyteksti, joka on riittävän pitkä hyväksyttäväksi."
    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"content": edited}).json()
    assert res["content"]["images"]["hero"]["id"] == "a"


# --- Tekstit: kielletyt fraasit, toisto, yksi lause ---

from app.demo_site import find_repeated_phrases, page_texts  # noqa: E402
from app.text_quality import find_forbidden_words, repeated_phrases  # noqa: E402


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("Autamme teitä valitsemaan.", "autamme"),
        ("Tarjoamme laadukasta hiustenhoitoa.", "tarjoamme laadukasta"),
        ("Tarjoamme laadukkaita palveluita.", "tarjoamme laadukasta"),
        ("Tervetuloa huolehtimaan hiuksistanne.", "tervetuloa huolehtimaan"),
    ],
)
def test_new_forbidden_phrases(text: str, label: str) -> None:
    assert label in find_forbidden_words(text)


def test_tervetuloa_and_tarjoamme_alone_are_fine() -> None:
    assert find_forbidden_words("Tervetuloa! Tarjoamme leikkaukset ja värit.") == []


def test_repeated_phrases_reports_longest_only() -> None:
    texts = ["Varatkaa aika puhelimitse.", "Leikkaukset ja värit. Varatkaa aika puhelimitse!"]
    assert repeated_phrases(texts) == ["varatkaa aika puhelimitse"]


def test_repeated_phrases_ignores_stopword_pairs_and_single_words() -> None:
    assert repeated_phrases(["Leikkaus ja se on nopea.", "Värjäys ja se on hidas.", "leikkaus"]) == []


def test_repeated_phrases_from_old_live_demo() -> None:
    # Taina v1: "Leikkaamme hiukset ja autamme teitä..." + "Hoidamme hiuksia ja autamme teitä..."
    texts = ["Leikkaamme hiukset ja autamme teitä ylläpitämään mallia.", "Hoidamme hiuksia ja autamme teitä valitsemaan hoitoa."]
    assert repeated_phrases(texts) == ["ja autamme teitä"]


def test_page_texts_include_template_and_business_name() -> None:
    texts = page_texts(_content(), business_name="Parturi-Kampaamo Taina Lantiainen", template="beauty")
    assert "Parturi-Kampaamo Taina Lantiainen" in texts
    assert TEMPLATES["beauty"].services_lead in texts
    assert "Hinnat ja ajanvaraus puhelimitse." in texts


def test_repetition_with_fixed_template_text_detected() -> None:
    content = _content(about="Olemme paikallinen liike Kauniaisissa. Varatkaa aika puhelimitse.")
    assert "varatkaa aika puhelimitse" in find_repeated_phrases(content, business_name="X", template="beauty")


def test_valid_test_content_has_no_repeats() -> None:
    assert find_repeated_phrases(_content(), business_name="Parturi-Kampaamo Taina Lantiainen", template="beauty") == []


def test_service_description_must_be_one_sentence() -> None:
    services = [{"name": "Leikkaus", "description": "Leikkaamme hiukset. Pesu kuuluu hintaan."}] + VALID["services"][1:]
    problems = content_violations(_content(services=services), allowed_text=ALLOWED)
    assert any("vain yksi lause" in p for p in problems)


def test_service_description_max_length() -> None:
    services = [{"name": "Leikkaus", "description": "x" * 141}] + VALID["services"][1:]
    with pytest.raises(ValidationError):
        _content(services=services)


def test_prompt_has_style_rules() -> None:
    from app.demo_site import DEMO_SYSTEM_PROMPT
    assert "TÄSMÄLLEEN YKSI lyhyt lause" in DEMO_SYSTEM_PROMPT
    assert "MIKÄÄN fraasi ei saa toistua sivulla" in DEMO_SYSTEM_PROMPT
    for word in ("autamme", "tarjoamme laadukasta", "tervetuloa huolehtimaan"):
        assert word in DEMO_SYSTEM_PROMPT


def test_repeated_phrases_trigger_one_retry(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI]
) -> None:
    repetitive = {**VALID, "about": "Olemme paikallinen liike. Leikkaukset, värit ja kampaukset koko perheelle."}
    demo_ready.replies = [json.dumps(repetitive), json.dumps(VALID)]
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert len(demo_ready.calls) == 2
    assert "toistuva fraasi" in demo_ready.calls[1]["messages"][1]["content"]
    assert demo["content"]["about"] == VALID["about"]


def test_repeated_phrases_twice_accepted_with_warning(
    client_a: TestClient, lead: dict[str, Any], demo_ready: type[FakeOpenAI], caplog: pytest.LogCaptureFixture
) -> None:
    import logging
    repetitive = {**VALID, "about": "Olemme paikallinen liike. Leikkaukset, värit ja kampaukset koko perheelle."}
    demo_ready.replies = [json.dumps(repetitive), json.dumps(repetitive)]
    with caplog.at_level(logging.WARNING, logger="app.main"):
        res = client_a.post(f"/leads/{lead['id']}/demo", json={})
    assert res.status_code == 200
    assert "toistuvat fraasit sivulla" in caplog.text


def test_eyebrow_repeating_business_name_is_detected() -> None:
    content = _content(hero_title="Parturi-kampaamo Kauniaisissa")
    assert "parturi kampaamo" in find_repeated_phrases(content, business_name="Parturi-Kampaamo Taina Lantiainen", template="beauty")


def test_people_regex_catches_clients() -> None:
    assert unsplash._PEOPLE_RE.search("A hair salon interior with hair products and clients")
    assert not unsplash._PEOPLE_RE.search("Three black salon chairs facing circular mirrors")


# --- Tuotemerkit hero-kuvassa ---

def _brand_photo(pid: str, *, people: bool = False, products: bool = False) -> DemoPhoto:
    return _photo(pid, people=people).model_copy(update={"has_products": products})


@pytest.mark.parametrize(
    ("alt", "description", "tags", "expected"),
    [
        ("Three black salon chairs facing circular mirrors", None, [], False),
        ("white shelf with hair products", None, [], True),
        ("salon interior", "Kevin Murphy brand display", [], True),
        ("salon interior", None, [{"title": "bottles"}, {"title": "salon"}], True),
        ("salon interior", None, [{"title": "cosmetics"}], True),
        ("empty barber chair by the window", None, [{"title": "barber"}, {"title": "chair"}], False),
    ],
)
def test_products_detected_from_alt_description_and_tags(
    alt: str, description: str | None, tags: list[dict[str, str]], expected: bool
) -> None:
    item = _api_photo("x", alt=alt)
    item["description"] = description
    item["tags"] = tags
    photo = unsplash._to_photo(item)
    assert photo is not None
    assert photo.has_products is expected


def test_hero_skips_brand_and_product_photos() -> None:
    candidates = [_brand_photo("shelf", products=True), _brand_photo("people", people=True), _brand_photo("clean")]
    hero, mood, options = unsplash.choose_images(candidates)
    assert hero is not None and hero.id == "clean"
    assert [o.id for o in options] == ["clean", "people", "shelf"]
    assert [m.id for m in mood] == ["people", "shelf"]  # tunnelmakuviin tuotteet ja ihmiset sallittuja


def test_hero_prefers_people_over_products_when_no_clean_photo() -> None:
    hero = unsplash.pick_hero([_brand_photo("shelf", products=True), _brand_photo("people", people=True)])
    assert hero is not None and hero.id == "people"


def test_hero_fallback_logs_warning_when_all_filtered(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    candidates = [_brand_photo("b1", products=True), _brand_photo("b2", products=True, people=True)]
    with caplog.at_level(logging.WARNING, logger="app.utils.unsplash"):
        hero = unsplash.pick_hero(candidates)
    assert hero is not None and hero.id == "b1"  # paras jäljelle jäänyt
    assert "ei puhdasta hero-kuvaa 2 ehdokkaasta" in caplog.text
    assert "tuotteita/merkkejä" in caplog.text


def test_clean_hero_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    with caplog.at_level(logging.WARNING, logger="app.utils.unsplash"):
        unsplash.pick_hero([_brand_photo("clean"), _brand_photo("b", products=True)])
    assert caplog.text == ""


def test_stored_photo_without_has_products_field_still_loads() -> None:
    data = _photo("old").model_dump()
    del data["has_products"]
    assert DemoPhoto.model_validate(data).has_products is False
