"""Remonttipohjat (remontti, lampopumppu): valinta, ei AI:ta, neutraali sisältö, pakolliset merkinnät, assetit ja julkaisu."""
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.demo_publish import asset_key
from app.demo_site import (
    ASSET_NAME_RE,
    TEMPLATES,
    DemoBusiness,
    DemoSender,
    DemoService,
    asset_series,
    demo_asset,
    google_reviews_url,
    hero_heading,
    phone_to_tel,
    is_static_template,
    render_demo_html,
    static_content,
    template_assets,
    template_for_lead,
)
from tests.conftest import FakeOpenAI
from tests.test_demo_publish import CONFIG, FakeStore

STATIC = ["remontti", "lampopumppu"]
BUSINESS = DemoBusiness(
    name="Putki & Saneeraus Oy", city="Espoo", address="Testitie 1, 02100 Espoo", phone="040 123 4567",
    maps_url="https://maps.google.com/?cid=1", place_id="ChIJabc123",
)
SENDER = DemoSender(name="Carolus Palin", company_name=None, phone=None, website="https://palinweb.fi", brand_name="Palin Web")


def render(template: str, business: DemoBusiness = BUSINESS, **content_updates: Any) -> str:
    content = static_content(template).model_copy(update=content_updates)
    return render_demo_html(
        template=template, color_scheme=next(iter(TEMPLATES[template].schemes)),
        content=content, business=business, sender=SENDER,
    )


@pytest.mark.parametrize("name,primary_type,expected", [
    ("Lämpöpumppu Hakola Oy", "service", "lampopumppu"),
    ("Maalämpö ja Ilmalämpö Oy", "general_contractor", "lampopumppu"),
    ("Jokin Oy", "hvac_contractor", "lampopumppu"),
    ("LVI ja lämpöpumput Virtanen", "plumber", "lampopumppu"),
    ("Espoon Kylpyhuoneremontit", "service", "remontti"),
    ("Saneeraus Laine", "service", "remontti"),
    ("LVI-Palvelu Laine", "service", "remontti"),
    ("Laatoitus Mäkinen", "point_of_interest", "remontti"),
    ("Putkiliike Virta", "plumber", "remontti"),
    ("Jokin Rakennus Oy", "general_contractor", "remontti"),
    ("Nimetön Oy", "general_contractor", "remontti"),
    ("Mini parturi", "barber_shop", "barber"),
    ("Kampaamo Aino", "hair_salon", "salon"),
    ("Aavikko Oy", "service", "services"),
    ("Alvinen Oy", "service", "services"),  # "lvi" vain sanana
    ("Sähkö Oy", "electrician", "services"),
])
def test_template_for_lead(name: str, primary_type: str, expected: str) -> None:
    assert template_for_lead(name, primary_type) == expected


def test_old_templates_are_not_static() -> None:
    assert [t for t in TEMPLATES if is_static_template(t)] == STATIC


@pytest.mark.parametrize("template", STATIC)
def test_static_content_is_valid_and_has_default_services(template: str) -> None:
    content = static_content(template)
    assert 3 <= len(content.services) <= 6
    assert content.service_area is None
    assert all(s.price is None for s in content.services)


@pytest.mark.parametrize("template", STATIC)
def test_mandatory_markers(template: str) -> None:
    html = render(template)
    assert 'name="robots" content="noindex, nofollow"' in html
    assert "Luonnos, tehnyt Palin Web" in html
    assert "Kuvat: tekoälyllä tehty kuvitus." in html
    assert "Teidän kohteenne kuvat tähän: ennen ja jälkeen samasta kulmasta." in html
    assert "Putki &amp; Saneeraus Oy" in html and "040 123 4567" in html and "Espoo" in html
    assert f'href="tel:{phone_to_tel(BUSINESS.phone)}"' in html
    # Lomake ei lähetä mitään: ei action-attribuuttia eikä method, vahvistus kertoo että kyse on luonnoksesta
    assert "<form id=\"quote\" novalidate>" in html
    assert "Tietoja ei lähetetty minnekään" in html


def services(*names: str) -> list[DemoService]:
    return [DemoService(name=n, description=f"Kuvaus palvelulle {n}.") for n in names]


@pytest.mark.parametrize("names,city,expected", [
    (("Kylpyhuoneremontti", "Saunaremontti", "WC-remontti"), "Espoo", "Kylpyhuone- ja saunaremontit Espoossa"),
    (("Putki- ja LVI-työt", "Saunaremontti"), "Vantaa", "Putki- ja LVI-työt ja saunaremontti Vantaalla"),
    (("Maalämpö", "Ilma-vesilämpöpumppu"), "Kauniainen", "Maalämpö ja ilma-vesilämpöpumppu Kauniaisissa"),
    (("Putkiasennus", "Pumppuasennus"), "Espoo", "Putki- ja pumppuasennus Espoossa"),
    (("Kylpyhuoneremontti", "Saunaremontti"), "Pikkukylä", "Kylpyhuone- ja saunaremontit, Pikkukylä"),
    (("Kylpyhuoneremontti", "Saunaremontti"), "", "Kylpyhuone- ja saunaremontit"),
    (("Kylpyhuoneremontti", "LVI-työt"), "Espoo", "Kylpyhuoneremontti ja LVI-työt Espoossa"),
])
def test_hero_heading_from_services_and_city(names: tuple[str, ...], city: str, expected: str) -> None:
    assert hero_heading(services(*names), city) == expected


@pytest.mark.parametrize("template", STATIC)
def test_hero_has_company_name_above_services_heading_and_short_subtitle(template: str) -> None:
    html = render(template)
    heading = hero_heading(static_content(template).services, BUSINESS.city)
    assert re.search(rf'<p class="yritys">Putki &amp; Saneeraus Oy</p>\s*<h1>{re.escape(heading)}</h1>', html)
    assert '<p class="lede">Pyydä tarjous lomakkeella tai soita 040 123 4567.</p>' in html
    no_phone = render(template, DemoBusiness(name="Ei Puhelinta Oy", city="Espoo", address=None, phone=None, maps_url=None))
    assert '<p class="lede">Pyydä tarjous lomakkeella.</p>' in no_phone


@pytest.mark.parametrize("template", STATIC)
def test_banner_and_footer_use_brand_name(template: str) -> None:
    html = render(template)
    assert "Luonnos, tehnyt Palin Web." in html and "Carolus" not in html


@pytest.mark.parametrize("template", STATIC)
def test_reviews_are_a_compact_row_in_contact_section(template: str) -> None:
    html = render(template)
    assert "Lukekaa" not in html and 'id="arvostelut-h"' not in html
    contact = html[html.index('id="tarjous"'):html.index('<form id="quote"')]
    assert 'class="arvostelut-rivi"' in contact and "<b>Arvostelut Googlessa</b>" in contact
    assert "Lue arvostelut Googlessa" in contact


@pytest.mark.parametrize("template", STATIC)
def test_csp_safe_html(template: str) -> None:
    html = render(template)
    assert " style=" not in html
    assert not re.search(r"<style|<script(?![^>]*\bsrc=)", html)
    assert "fonts.googleapis" not in html
    assert "onclick=" not in html


@pytest.mark.parametrize("template", STATIC)
def test_no_invented_claims(template: str) -> None:
    text = re.sub(r"<[^>]+>", " ", render(template)).lower()
    for word in ("viikkoa", "viikon", "takuu", "sertifioi", "kse 2013", "ilman maksua", "maksuton", "työnjohtaja",
                 "tähti", "★", "arvosana", ".example", "numeronne tähän", "vuodesta", "perustettu", "alkaen"):
        assert word not in text, word
    assert not re.search(r"\d\s?€", text.split("kotitalousvähennys yhteensä")[0].split("paljonko saatte")[0])


@pytest.mark.parametrize("template", STATIC)
def test_service_area_section_only_when_set(template: str) -> None:
    assert "Toimialue" not in render(template)
    html = render(template, service_area="Espoo ja Kauniainen")
    assert "Toimialue" in html and "Espoo ja Kauniainen" in html


@pytest.mark.parametrize("template", STATIC)
def test_services_come_from_content(template: str) -> None:
    from app.demo_site import DemoService
    html = render(template, services=[DemoService(name=f"Palvelu {i}", description=f"Kuvaus numero {i}.") for i in range(3)])
    assert "Palvelu 2" in html and "Kuvaus numero 1." in html
    assert "Kylpyhuoneremontti" not in html


@pytest.mark.parametrize("template", STATIC)
def test_reviews_link_without_rating_or_count(template: str) -> None:
    html = render(template)
    assert 'href="https://search.google.com/local/reviews?placeid=ChIJabc123"' in html
    assert "Lue arvostelut Googlessa" in html
    assert not re.search(r"\d[,.]\d\s*(/|·)|\(\d+\)", html)


@pytest.mark.parametrize("place_id,maps,expected", [
    ("ChIJabc", "https://maps.google.com/?cid=1", "https://search.google.com/local/reviews?placeid=ChIJabc"),
    ("manual-1", "https://maps.google.com/?cid=1", "https://maps.google.com/?cid=1"),
    ("dev-1", None, None),
    (None, None, None),
])
def test_google_reviews_url(place_id: str | None, maps: str | None, expected: str | None) -> None:
    assert google_reviews_url(place_id, maps) == expected


def test_no_reviews_section_without_any_link() -> None:
    html = render("remontti", DemoBusiness(name="Ei Linkkiä Oy", city="Espoo", address=None, phone=None, maps_url=None))
    assert "Lue arvostelut" not in html
    assert 'class="mbar yksi"' in html
    assert "Numeronne" not in html and 'href="tel:' not in html


def test_heat_pump_calculator_and_tax_numbers_unchanged() -> None:
    html = render("lampopumppu")
    js = (demo_asset("lampopumppu", "sivu.js") or pytest.fail()).body.decode()
    assert "ded(work,ppl,0.60,3500)" in js and "ded(work,ppl,0.40,2100)" in js
    assert "60 % työn osuudesta, enintään 3 500 €" in html and "Muu työ: 40 %, enintään 2 100 €" in html
    assert 'id="oil-lbl"' in html
    remontti_js = (demo_asset("remontti", "sivu.js") or pytest.fail()).body.decode()
    assert "per*0.40-150,2100" in remontti_js
    assert "40 % työn osuudesta, omavastuu 150 € ja enintään 2 100 €" in render("remontti")


@pytest.mark.parametrize("template", STATIC)
def test_assets_exist_and_are_referenced_by_hash(template: str) -> None:
    html = render(template)
    available = {a.url for a in template_assets(template)}
    for url in re.findall(r'(?:src|href)="(a/[^"]+)"', html):
        assert url in available, url
    frames_f, frames_m = asset_series(template, "f"), asset_series(template, "m")
    assert len(frames_f) == len(frames_m) == 121
    assert f'data-f="{" ".join(a.url for a in frames_f)}"' in html
    for asset in template_assets(template):
        assert ASSET_NAME_RE.fullmatch(asset.name), asset.name
    assert all(a.digest for a in template_assets(template))
    # Fontit ja CSS:n viittaukset versioitu: tyylit viittaa fontteihin tiivisteellä
    css = (demo_asset(template, "tyylit.css") or pytest.fail()).body.decode()
    assert re.search(r'url\("[a-z0-9-]+\.woff2\?v=[0-9a-f]{10}"\)', css)
    assert "notesToggle" not in css and ".demo-bar" not in css


def test_shared_asset_total_size_is_reasonable() -> None:
    total = sum(len(a.body) for t in STATIC for a in template_assets(t))
    assert total < 20_000_000


# --- Rajapinta ---

@pytest.fixture
def no_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.main.OPENAI_API_KEY", "")
    FakeOpenAI.calls = []


def test_generate_demo_skips_ai_for_renovation_lead(
    client_a: TestClient, make_lead: Any, sender_profile: dict[str, Any], no_ai: None
) -> None:
    lead = make_lead(name="Kylpyhuoneremontit Laine", city="Espoo", primary_type="service", phone="040 111 2222",
                     google_place_id="ChIJxyz")
    res = client_a.post(f"/leads/{lead['id']}/demo", json={})
    assert res.status_code == 200, res.text
    demo = res.json()
    assert demo["template"] == "remontti" and demo["color_scheme"] == "kalvo"
    assert demo["content"]["images"]["hero"] is None
    assert FakeOpenAI.calls == []
    preview = client_a.get(f"/demo/{demo['public_path']}")
    assert preview.status_code == 200 and "noindex" in preview.headers["x-robots-tag"]
    assert "placeid=ChIJxyz" in preview.text


def test_heat_pump_lead_gets_heat_pump_template(
    client_a: TestClient, make_lead: Any, sender_profile: dict[str, Any], no_ai: None
) -> None:
    lead = make_lead(name="Lämpöpumppu Hakola", city="Vantaa", primary_type="service")
    assert client_a.post(f"/leads/{lead['id']}/demo", json={}).json()["template"] == "lampopumppu"


def test_other_templates_still_need_openai(
    client_a: TestClient, make_lead: Any, sender_profile: dict[str, Any], no_ai: None
) -> None:
    lead = make_lead(name="Kahvila Aamu", city="Espoo", primary_type="cafe")
    assert client_a.post(f"/leads/{lead['id']}/demo", json={}).status_code == 500


def test_edit_services_and_area_then_regenerate_keeps_them(
    client_a: TestClient, make_lead: Any, sender_profile: dict[str, Any], no_ai: None
) -> None:
    lead = make_lead(name="Saneeraus Laine", city="Espoo", primary_type="service")
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    content = {k: v for k, v in demo["content"].items() if k not in ("opening_hours", "opening_periods", "images", "site_based", "timma")}
    content["services"] = [{"name": f"Oma {i}", "description": f"Oma kuvaus {i} tähän."} for i in range(3)]
    content["service_area"] = "Espoo ja Kauniainen"
    patched = client_a.patch(f"/leads/{lead['id']}/demo", json={"content": content})
    assert patched.status_code == 200, patched.text
    again = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert [s["name"] for s in again["content"]["services"]] == ["Oma 0", "Oma 1", "Oma 2"]
    assert again["content"]["service_area"] == "Espoo ja Kauniainen"
    html = client_a.get(f"/demo/{again['public_path']}").text
    assert "Oma kuvaus 1 tähän." in html and "Espoo ja Kauniainen" in html


def test_template_switch_between_renovation_and_others(
    client_a: TestClient, make_lead: Any, sender_profile: dict[str, Any], no_ai: None
) -> None:
    lead = make_lead(name="Saneeraus Laine", city="Espoo", primary_type="service")
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    switched = client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "lampopumppu"}).json()
    assert switched["template"] == "lampopumppu"
    assert switched["content"]["services"][0]["name"] == "Maalämpö"
    assert client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "cafe"}).status_code == 422
    assert demo["template"] == "remontti"


def check_services(client: TestClient, lead_id: int) -> None:
    demo = client.get(f"/leads/{lead_id}/demo").json()
    content = {k: v for k, v in demo["content"].items() if k not in ("opening_hours", "opening_periods", "images", "site_based", "timma")}
    content["services_checked"] = True
    assert client.patch(f"/leads/{lead_id}/demo", json={"content": content}).status_code == 200


def test_publish_blocked_until_services_checked(
    client_a: TestClient, make_lead: Any, sender_profile: dict[str, Any], no_ai: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FakeStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: store)
    monkeypatch.setattr("app.demo_publish._uploaded_assets", set())
    lead = make_lead(name="Saneeraus Laine", city="Espoo", primary_type="service")
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert demo["content"]["services_checked"] is False
    blocked = client_a.post(f"/leads/{lead['id']}/demo/publish")
    assert blocked.status_code == 409 and "Services not checked" in blocked.json()["detail"]
    assert store.headers == {}
    check_services(client_a, lead["id"])
    assert client_a.post(f"/leads/{lead['id']}/demo/publish").status_code == 200
    # Regenerate säilyttää tarkistetun tilan, pohjan vaihto palauttaa oletuslistan ja vaatii tarkistuksen uudelleen
    assert client_a.post(f"/leads/{lead['id']}/demo", json={}).json()["content"]["services_checked"] is True
    switched = client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "lampopumppu"}).json()
    assert switched["content"]["services_checked"] is False


def test_autodemo_creates_draft_but_does_not_publish_unchecked_services(
    client_a: TestClient, make_lead: Any, sender_profile: dict[str, Any], no_ai: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FakeStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: store)
    lead = make_lead(name="Saneeraus Laine", city="Espoo", primary_type="service")
    res = client_a.post(f"/leads/{lead['id']}/autodemo")
    assert res.status_code == 409 and "Services not checked" in res.json()["detail"]
    assert client_a.get(f"/leads/{lead['id']}/demo").json()["status"] == "draft"


def test_publish_uploads_shared_assets_once(
    client_a: TestClient, make_lead: Any, sender_profile: dict[str, Any], no_ai: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FakeStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: store)
    monkeypatch.setattr("app.demo_publish._uploaded_assets", set())
    puts: list[str] = []
    original_put = store.put

    def tracking_put(key: str, body: bytes, **kwargs: Any) -> None:
        puts.append(key)
        original_put(key, body, **kwargs)

    monkeypatch.setattr(store, "put", tracking_put)
    ids = []
    for name in ("Saneeraus Laine", "Kylpyhuone Virta"):
        lead = make_lead(name=name, city="Espoo", primary_type="service")
        ids.append(lead["id"])
        client_a.post(f"/leads/{lead['id']}/demo", json={})
        check_services(client_a, lead["id"])
        assert client_a.post(f"/leads/{lead['id']}/demo/publish").status_code == 200
    expected = {asset_key(a) for a in template_assets("remontti")}
    assert expected <= set(puts)
    assert len([k for k in puts if k.startswith("assets/")]) == len(expected)
    assert len([k for k in puts if k.startswith("demos/")]) == 2
    assert all(store.headers[k][2] == {"format": "2"} for k in puts if k.startswith("demos/"))
