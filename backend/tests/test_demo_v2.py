"""Versio 2 -demopohjat: erilliset tiedostot, aukioloajat, palettien kontrastit, julkaisu ja esikatselu."""
import json
import re
from pathlib import Path
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from app.demo_publish import ASSET_CACHE_CONTROL, asset_key, publish_html
from app.demo_site import (
    ASSET_DIR,
    TEMPLATES,
    DemoBusiness,
    DemoSender,
    DemoStoredContent,
    OpeningPeriod,
    Palette,
    aukiolo_attrs,
    demo_asset,
    hours_summary,
    periods_from_google,
    price_note_for,
    render_demo_html,
    template_assets,
    week_rows,
)
from tests.conftest import FakeOpenAI
from tests.test_demo_publish import CONFIG, FakeStore
from tests.test_demo_site import VALID

V2_TEMPLATES = [t for t, v in TEMPLATES.items() if v.version >= 2]
WORKER = (Path(__file__).resolve().parents[2] / "worker" / "src" / "index.ts").read_text()


def _p(day: int, open_: str, close: str) -> OpeningPeriod:
    return OpeningPeriod(day=day, open=open_, close=close)


def _g(day: int, hour: int, minute: int = 0) -> dict[str, int]:
    return {"day": day, "hour": hour, "minute": minute}


# --- Aukioloajat ---

def test_periods_from_google_regular_and_lunch_break() -> None:
    raw = [
        {"open": _g(1, 10), "close": _g(1, 12)},
        {"open": _g(1, 13), "close": _g(1, 17, 30)},
        {"open": _g(6, 9), "close": _g(6, 16)},
    ]
    assert periods_from_google(raw) == [_p(1, "10:00", "12:00"), _p(1, "13:00", "17:30"), _p(6, "09:00", "16:00")]


def test_periods_from_google_overnight_is_split_at_midnight() -> None:
    raw = [{"open": _g(5, 18), "close": _g(6, 2)}, {"open": _g(6, 18), "close": _g(0, 0)}]
    assert periods_from_google(raw) == [_p(5, "18:00", "24:00"), _p(6, "00:00", "02:00"), _p(6, "18:00", "24:00")]


def test_periods_from_google_always_open_and_garbage() -> None:
    assert periods_from_google([{"open": _g(0, 0)}]) == [_p(d, "00:00", "24:00") for d in range(7)]
    assert periods_from_google(None) == []
    assert periods_from_google([{"open": "x"}, 5, {"open": _g(1, 25), "close": _g(1, 26)}]) == []


def test_aukiolo_attrs_use_finnish_day_keys() -> None:
    periods = [_p(1, "10:00", "12:00"), _p(1, "13:00", "17:00"), _p(0, "11:00", "15:00")]
    assert aukiolo_attrs(periods) == {"ma": "10:00-12:00,13:00-17:00", "su": "11:00-15:00"}


def test_week_rows_and_summary_from_periods() -> None:
    periods = [_p(d, "10:00", "19:00") for d in range(1, 6)] + [_p(6, "10:00", "15:30")]
    rows = week_rows(DemoStoredContent(**VALID, opening_periods=periods))
    assert [(r.paiva, r.label, r.value, r.closed) for r in rows][4:] == [
        (5, "Perjantai", "10–19", False), (6, "Lauantai", "10–15.30", False), (7, "Sunnuntai", "suljettu", True),
    ]
    assert hours_summary(rows) == "Ma–pe 10–19, la 10–15.30, su suljettu"


def test_week_rows_fall_back_to_google_descriptions() -> None:
    content = DemoStoredContent(**VALID, opening_hours=["maanantai: 9.00–17.00", "sunnuntai: Suljettu"])
    rows = week_rows(content)
    assert [(r.paiva, r.value, r.closed) for r in rows] == [(1, "9.00–17.00", False), (7, "suljettu", True)]


def test_aukiolo_js_reads_comma_separated_ranges() -> None:
    js = (ASSET_DIR / "yhteinen" / "aukiolo.js").read_text()
    assert 'arvo.split(",")' in js


# --- Tiedostot ---

def test_assets_are_versioned_and_css_references_versioned_fonts() -> None:
    css = demo_asset("cafe", "tyylit.css")
    font = demo_asset("cafe", "young-serif.woff2")
    assert css is not None and font is not None
    assert re.fullmatch(r"[0-9a-f]{10}", css.digest)
    assert css.url == f"a/cafe/tyylit.css?v={css.digest}"
    assert f'url("young-serif.woff2?v={font.digest}")' in css.body.decode()
    assert font.content_type == "font/woff2"


@pytest.mark.parametrize("group,name", [
    ("cafe", "OFL-young-serif.txt"), ("cafe", "../yhteinen/aukiolo.js"), ("Cafe", "tyylit.css"),
    ("cafe", "puuttuu.css"), ("..", "tyylit.css"),
])
def test_demo_asset_rejects_unknown_files(group: str, name: str) -> None:
    assert demo_asset(group, name) is None


@pytest.mark.parametrize("template", V2_TEMPLATES)
def test_template_assets_cover_everything_the_page_references(template: str) -> None:
    html = _render(template)
    referenced = set(re.findall(r'(?:href|src)="(a/[^"]+)"', html))
    available = {a.url for a in template_assets(template)}
    assert referenced and referenced <= available
    # Fontit CSS:n kautta
    for asset in template_assets(template):
        if asset.name.endswith(".css"):
            for font, version in re.findall(r'url\("([^"?]+)\?v=([0-9a-f]+)"\)', asset.body.decode()):
                assert f"a/{asset.group}/{font}?v={version}" in available


def test_v1_templates_have_no_assets() -> None:
    assert template_assets("beauty") == []


def test_worker_asset_regexes_match_backend() -> None:
    assert r"const ASSET_PATH_RE = /^a\/([a-z]{2,20})\/([a-z0-9-]+\.(css|js|woff2))$/;" in WORKER
    assert "const ASSET_DIGEST_RE = /^[0-9a-f]{10}$/;" in WORKER


# --- Paletit: kontrastit tyylit.css:stä ---

def _luminance(hex_color: str) -> float:
    channels = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted([_luminance(a), _luminance(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _palette_tokens(template: str, palette: str) -> dict[str, str]:
    css = (ASSET_DIR / template / "tyylit.css").read_text()
    # Kaikki saman valitsimen lohkot (myös mediakyselyjen :root, joissa ei ole värejä)
    blocks: dict[str, str] = {}
    for selector, body in re.findall(r'(:root|\[data-paletti="[a-z]+"\])\s*\{([^}]*)\}', css):
        blocks[selector] = blocks.get(selector, "") + body
    tokens: dict[str, str] = {}
    for selector in (":root", f'[data-paletti="{palette}"]'):
        tokens.update(re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", blocks.get(selector, "")))
    return tokens


# (teksti, tausta) -parit, joiden pitää olla ≥ 4,5:1, pohjittain
CONTRAST_PAIRS: dict[str, list[tuple[str, str]]] = {
    "cafe": [
        *[(f"savy-{n}-teksti", f"savy-{n}") for n in range(1, 5)],
        *[(f"savy-{n}-toinen", f"savy-{n}") for n in range(1, 5)],
        ("#FFFFFF", "korostus"), ("#FFFFFF", "korostus-tumma"),
    ],
    "salon": [
        ("muste", "usva"), ("harmaa", "usva"), ("jarvi", "usva"), ("#FFFFFF", "jarvi"), ("#FFFFFF", "jarvi-syva"),
        ("kaisla", "jarvi"), ("jarvi-teksti", "jarvi"), ("jarvi-teksti", "jarvi-syva"),
    ],
    "barber": [
        ("musta", "liitu"), ("harmaa", "liitu"), ("musta", "betoni"), ("harmaa-betoni", "betoni"),
        ("liitu", "musta"), ("harmaa-musta", "musta"), ("kyltti-teksti", "kyltti"), ("kyltti-musta", "musta"),
    ],
}


@pytest.mark.parametrize(
    "template,palette",
    [(t, p) for t in V2_TEMPLATES for p in TEMPLATES[t].schemes],
)
def test_palette_contrast_is_at_least_aa(template: str, palette: str) -> None:
    tokens = _palette_tokens(template, palette)
    for fg, bg in CONTRAST_PAIRS[template]:
        fg_hex = fg if fg.startswith("#") else tokens[fg]
        ratio = _contrast(fg_hex, tokens[bg])
        assert ratio >= 4.5, f"{template}/{palette}: {fg} on {bg} = {ratio:.2f}"


@pytest.mark.parametrize("template", V2_TEMPLATES)
def test_every_palette_has_css_block_and_theme_color(template: str) -> None:
    css = (ASSET_DIR / template / "tyylit.css").read_text()
    schemes = TEMPLATES[template].schemes
    assert 2 <= len(schemes) <= 3
    for i, (palette, scheme) in enumerate(schemes.items()):
        assert isinstance(scheme, Palette)
        # Ensimmäinen paletti on :root-oletus, muut omina lohkoinaan
        assert i == 0 or f'[data-paletti="{palette}"]' in css


# --- Renderöinti ---

BUSINESS = DemoBusiness(
    name="Kahvila ja leipomo Vanha Postitalo", city="Porvoo", address="Esimerkkikatu 4, 06100 Porvoo, Suomi",
    phone="050 000 0000", maps_url="https://maps.google.com/?cid=1",
)
SENDER = DemoSender(name="Carolus Palin", company_name="Palin Web", phone="040 111 2222", website="https://palinweb.fi")


def _render(template: str, periods: Optional[list[OpeningPeriod]] = None, palette: Optional[str] = None) -> str:
    content = DemoStoredContent(**VALID, price_note=price_note_for(template), opening_periods=periods or [])
    return render_demo_html(
        template=template, color_scheme=palette or next(iter(TEMPLATES[template].schemes)),
        content=content, business=BUSINESS, sender=SENDER,
    )


@pytest.mark.parametrize("template", V2_TEMPLATES)
def test_v2_page_has_no_inline_styles_or_scripts(template: str) -> None:
    html = _render(template, [_p(1, "10:00", "17:00")])
    assert "<style" not in html
    assert " style=" not in html
    scripts = re.findall(r"<script[^>]*>", html)
    assert len(scripts) == 1 and re.fullmatch(r'<script defer src="a/yhteinen/aukiolo\.js\?v=[0-9a-f]{10}">', scripts[0])


@pytest.mark.parametrize("template", V2_TEMPLATES)
def test_v2_page_keeps_demo_banner_and_noindex(template: str) -> None:
    html = _render(template)
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert "Tämä on luonnos, jonka Carolus Palin teki yritykselle Kahvila ja leipomo Vanha Postitalo." in html
    assert "Luonnos – ei virallinen sivu" in html


@pytest.mark.parametrize("template", V2_TEMPLATES)
def test_v2_hours_render_machine_readable_and_static_week(template: str) -> None:
    html = _render(template, [_p(1, "10:00", "12:00"), _p(1, "13:00", "17:00")])
    assert 'id="aukiolo" data-ma="10:00-12:00,13:00-17:00"' in html
    assert 'data-paiva="1"' in html and "10–12, 13–17" in html
    assert "data-tanaan" in html
    # Kahvilan ja parturin yläpalkissa on tila ("Auki nyt"), kampaamon yläpalkissa Varaa aika -nappi
    assert ("data-tila" in html) == (template in ("cafe", "barber"))


@pytest.mark.parametrize("template", V2_TEMPLATES)
def test_v2_without_hours_omits_live_status_and_script(template: str) -> None:
    html = _render(template)
    assert 'id="aukiolo"' not in html
    assert "aukiolo.js" not in html
    assert "data-tila" not in html and "data-tanaan" not in html


@pytest.mark.parametrize("template,palette", [(t, p) for t in V2_TEMPLATES for p in TEMPLATES[t].schemes])
def test_v2_palette_attribute(template: str, palette: str) -> None:
    assert f'data-paletti="{palette}"' in _render(template, palette=palette)


def test_cafe_has_no_booking_wording() -> None:
    assert "ajanvaraus" not in _render("cafe").lower()


# --- API: generointi, pohjan vaihto, esikatselu, julkaisu ---

@pytest.fixture
def cafe_lead(make_lead: Any) -> dict[str, Any]:
    return make_lead(
        name="Kahvila Kuppi", city="Espoo", address="Esimerkkikatu 12", phone="040 000 0000",
        website_status="NO WEBSITE", primary_type="coffee_shop", maps_url="https://maps.google.com/?cid=1",
    )


@pytest.fixture
def cafe_demo(client_a: TestClient, cafe_lead: dict[str, Any], fake_openai: type[FakeOpenAI],
              sender_profile: dict[str, Any]) -> dict[str, Any]:
    fake_openai.reply = json.dumps(VALID)
    return client_a.post(f"/leads/{cafe_lead['id']}/demo", json={}).json()


def test_cafe_lead_gets_cafe_template_and_its_price_note(cafe_demo: dict[str, Any]) -> None:
    assert cafe_demo["template"] == "cafe"
    assert cafe_demo["color_scheme"] == "paahto"
    assert cafe_demo["content"]["price_note"] == price_note_for("cafe")


def test_template_switch_swaps_default_price_note_but_keeps_custom(client_a: TestClient, cafe_demo: dict[str, Any]) -> None:
    lead_id = cafe_demo["lead_id"]
    res = client_a.patch(f"/leads/{lead_id}/demo", json={"template": "services"}).json()
    assert res["content"]["price_note"] == price_note_for("services")
    edited = {k: v for k, v in res["content"].items() if k not in ("opening_hours", "opening_periods", "images", "site_based")}
    edited["price_note"] = "Kahvi kolme euroa, pulla neljä."
    client_a.patch(f"/leads/{lead_id}/demo", json={"content": edited})
    res = client_a.patch(f"/leads/{lead_id}/demo", json={"template": "cafe"}).json()
    assert res["content"]["price_note"] == "Kahvi kolme euroa, pulla neljä."


def test_preview_of_v2_demo_has_strict_csp_and_serves_assets(client_a: TestClient, cafe_demo: dict[str, Any]) -> None:
    res = client_a.get(f"/demo/{cafe_demo['public_path']}")
    csp = res.headers["content-security-policy"]
    assert "style-src 'self'" in csp and "script-src 'self'" in csp and "unsafe-inline" not in csp
    css_url = re.search(r'href="(a/cafe/tyylit\.css\?v=[0-9a-f]+)"', res.text)
    assert css_url is not None
    asset = client_a.get(f"/demo/{css_url.group(1)}")
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("text/css")
    assert asset.headers["access-control-allow-origin"] == "*"
    assert client_a.get("/demo/a/cafe/OFL-young-serif.txt").status_code == 404
    assert client_a.get("/demo/a/cafe/..%2F..%2Fdemo_site.py").status_code == 404


def test_preview_of_v1_demo_keeps_inline_csp(client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI],
                                             sender_profile: dict[str, Any]) -> None:
    fake_openai.reply = json.dumps(VALID)
    lead = make_lead(name="Putkiliike", city="Espoo", website_status="NO WEBSITE", primary_type="plumber")
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert "style-src 'unsafe-inline'" in client_a.get(f"/demo/{demo['public_path']}").headers["content-security-policy"]


def test_publish_uploads_assets_before_html_with_format_metadata(
    client_a: TestClient, cafe_demo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FakeStore()
    order: list[str] = []
    original_put = store.put

    def tracking_put(key: str, body: bytes, **kwargs: Any) -> None:
        order.append(key)
        original_put(key, body, **kwargs)

    monkeypatch.setattr(store, "put", tracking_put)
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: store)
    monkeypatch.setattr("app.demo_publish._uploaded_assets", set())
    res = client_a.post(f"/leads/{cafe_demo['lead_id']}/demo/publish")
    assert res.status_code == 200
    html_key = f"demos/{cafe_demo['public_path']}.html"
    assert order[-1] == html_key
    assert store.headers[html_key][2] == {"format": "2"}
    expected = {asset_key(a) for a in template_assets("cafe")}
    assert expected <= set(order[:-1])
    css_key = next(k for k in expected if k.endswith("tyylit.css"))
    assert store.headers[css_key][:2] == ("text/css; charset=utf-8", ASSET_CACHE_CONTROL)


def test_existing_assets_are_not_uploaded_again(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    monkeypatch.setattr("app.demo_publish._uploaded_assets", set())
    assets = template_assets("cafe")
    for a in assets:
        store.objects[asset_key(a)] = (b"old", None)
    publish_html(store, "kuppi-a2b3c", "<html>", None, assets)
    assert all(store.objects[asset_key(a)][0] == b"old" for a in assets)
    assert "demos/kuppi-a2b3c.html" in store.objects


def test_v1_publish_has_no_format_metadata() -> None:
    store = FakeStore()
    publish_html(store, "putki-a2b3c", "<html>", None)
    assert store.headers["demos/putki-a2b3c.html"][2] == {}
    assert list(store.objects) == ["demos/putki-a2b3c.html"]


# --- Kuvat ---

from app.utils import unsplash  # noqa: E402


def _photo(pid: str, people: bool = False) -> unsplash.DemoPhoto:
    return unsplash.DemoPhoto(id=pid, raw_url=f"https://images.unsplash.com/{pid}", photographer_name="N",
                              photographer_url="https://unsplash.com/@n", download_location="x", has_people=people)


def test_cafe_queries_prefer_overhead_subject() -> None:
    assert unsplash.image_queries("coffee_shop", "cafe") == ["coffee cup from above", "cafe pastries"]
    assert unsplash.image_queries("bakery", "cafe")[0] == "pastries from above"
    assert unsplash.uses_both_queries("cafe") and not unsplash.uses_both_queries("beauty")


def test_mixed_results_hero_from_first_query_mood_from_second() -> None:
    first = [_photo("p1", people=True), _photo("a1"), _photo("a2")]
    second = [_photo("b1"), _photo("b2"), _photo("b3"), _photo("b4")]
    mixed = unsplash.mix_results(first, second)
    assert [p.id for p in mixed] == ["a1", "b1", "b2", "b3", "p1", "b4", "a2"]
    hero, mood, _ = unsplash.choose_images(mixed)
    assert hero is not None and hero.id == "a1"
    assert [p.id for p in mood] == ["b1", "b2", "b3"]


# --- Väitteet, joita lähdetiedoissa ei ole ---

from app.demo_site import DEMO_SYSTEM_PROMPT, DemoAIContent, content_violations  # noqa: E402

_NAME = "Kahvila Kuppi Espoo Esimerkkikatu 12"


def _with(**fields: str) -> DemoAIContent:
    return DemoAIContent(**{**VALID, **fields})


@pytest.mark.parametrize("field,text,label", [
    ("about", "Leivomme pullat itse joka aamu ja keitämme kahvin tilauksesta.", "oma valmistus"),
    ("about", "Kahvila on vanhan talon kivijalassa, ja kahvit keitetään tilauksesta.", "sijainti"),
    ("about_title", "Kahvila keskellä korttelia", "sijainti"),
    ("hero_title", "Kahvia ja pullaa kulman takana", "sijainti"),
    ("about", "Olemme perheyritys, ja kahvit keitetään tilauksesta joka päivä.", "perhe tai omistajat"),
    ("about", "Pieni kahvila, jossa kahvit keitetään tilauksesta ja leivonnaiset ovat tiskillä.", "koko"),
    ("about", "Kotitekoiset leivonnaiset ja kahvit tilauksesta tiskiltä ja mukaan.", "oma valmistus"),
    ("about_title", "Pitkät perinteet kahvilassa", "historia"),
    ("hero_subtitle", "Kahvia ja leivonnaisia omassa leipomossa tehtyinä.", "oma valmistus"),
])
def test_claims_without_source_are_rejected(field: str, text: str, label: str) -> None:
    problems = content_violations(_with(**{field: text}), allowed_text=_NAME)
    assert any(p.startswith(f"{field}: väite") and label in p for p in problems), problems


@pytest.mark.parametrize("field,text,source", [
    ("about", "Leivomme pullat itse joka aamu ja keitämme kahvin tilauksesta.", "Leivomme kaiken itse aamuisin."),
    ("about", "Kahvila on vanhan talon kivijalassa, ja kahvit keitetään tilauksesta.", "Löydät meidät kivijalasta, vanhasta talosta."),
    ("about", "Olemme perheyritys, ja kahvit keitetään tilauksesta joka päivä.", "Perheemme kahvila palvelee teitä."),
    ("about_title", "Leipomo ja kahvila samassa talossa", "Kahvila ja leipomo Vanha Postitalo"),
])
def test_claims_supported_by_name_or_deep_scan_are_allowed(field: str, text: str, source: str) -> None:
    problems = content_violations(_with(**{field: text}), allowed_text=f"{_NAME} {source}")
    assert not [p for p in problems if "väite" in p], problems


def test_service_descriptions_are_not_checked_for_business_claims() -> None:
    services = [{"name": "Leivonnaiset", "description": "Pullat ja piirakat leivotut samana aamuna."}, *VALID["services"][1:]]
    problems = content_violations(_with(services=services), allowed_text=_NAME)  # type: ignore[arg-type]
    assert not [p for p in problems if "väite" in p]


def test_prompt_forbids_unsupported_claims() -> None:
    assert "VAIN sitä, mikä lukee yrityksen nimessä, osoitteessa tai VERKKOSIVUN SISÄLLÖSSÄ" in DEMO_SYSTEM_PROMPT
    assert "keskustassa" not in DEMO_SYSTEM_PROMPT.split("about_title")[1].split("\n")[0]


def test_unsupported_claim_triggers_retry_then_502(
    client_a: TestClient, cafe_lead: dict[str, Any], fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    claim = json.dumps({**VALID, "about": "Leivomme kaiken itse ja kahvit keitetään tilauksesta aamuisin."})
    fake_openai.replies = [claim, claim]
    res = client_a.post(f"/leads/{cafe_lead['id']}/demo", json={})
    assert res.status_code == 502
    assert "oma valmistus" in res.json()["detail"]


# --- Kahvilan yhteystieto-osion tumma kuva ---

def _colored(pid: str, color: str) -> unsplash.DemoPhoto:
    return _photo(pid).model_copy(update={"color": color})


def test_cafe_last_mood_image_is_darkest_dark_candidate() -> None:
    pool = [_colored("h", "#f0f0f0"), _colored("a", "#d9c8b0"), _colored("d1", "#3a2a20"),
            _colored("b", "#c0a080"), _colored("d2", "#141010")]
    hero, mood, _ = unsplash.choose_images(pool, "cafe")
    assert hero is not None and hero.id == "h"
    assert [p.id for p in mood] == ["a", "d1", "d2"]


def test_cafe_without_dark_candidate_has_no_contact_image() -> None:
    pool = [_colored(c, "#e0e0e0") for c in "habc"]
    _, mood, _ = unsplash.choose_images(pool, "cafe")
    assert len(mood) == 2
    html = render_demo_html(
        template="cafe", color_scheme="paahto", business=BUSINESS, sender=SENDER,
        content=DemoStoredContent(**VALID, images=unsplash_images(pool)),
    )
    assert 'class="yhteys-kuva"' not in html


def unsplash_images(pool: list[unsplash.DemoPhoto]) -> Any:
    from app.demo_site import DemoImages
    hero, mood, options = unsplash.choose_images(pool, "cafe")
    return DemoImages(hero=hero, mood=mood, options=options)


def test_dark_candidate_outside_top_options_is_pulled_in() -> None:
    pool = [_colored(f"l{i}", "#eeeeee") for i in range(10)] + [_colored("dark", "#101010")]
    _, mood, options = unsplash.choose_images(pool, "cafe")
    assert options[-1].id == "dark" and mood[-1].id == "dark"


def test_other_templates_keep_plain_mood_order() -> None:
    pool = [_colored("h", "#f0f0f0"), _colored("d", "#101010"), _colored("a", "#eeeeee"), _colored("b", "#dddddd")]
    _, mood, _ = unsplash.choose_images(pool, "beauty")
    assert [p.id for p in mood] == ["d", "a", "b"]


# --- Kampaamo: kasvoriski, aiheen ulkopuoliset kuvat, neljä tunnelmakuvaa ---

@pytest.mark.parametrize("text,risky", [
    ("Close-up of a person's dark curly hair", False),
    ("the back of a woman's head with long dark hair", False),
    ("hands holding scissors and a comb", False),
    ("brown hair on black background", False),
    ("Close-up of a young woman with braided hair", True),
    ("a woman is cutting another woman's hair with scissors", True),
    ("woman smiling in salon", True),
    ("Close up of a person's eyes with braided hair", True),
])
def test_face_risk_from_caption(text: str, risky: bool) -> None:
    assert unsplash.face_risk(text) is risky


def _alt(pid: str, alt: str, face: bool = False) -> unsplash.DemoPhoto:
    return _photo(pid).model_copy(update={"alt": alt, "face_risk": face})


def test_salon_queries_ask_for_finished_hair_and_nails_keep_industry_queries() -> None:
    assert unsplash.image_queries("hair_salon", "salon") == ["glossy wavy hair close up", "braided hairstyle back view"]
    assert unsplash.image_queries("beauty_salon", "salon")[0] == "glossy wavy hair close up"
    assert unsplash.uses_both_queries("salon")
    assert unsplash.image_queries("nail_salon", "salon") == ["nail salon", "manicure"]


def test_salon_drops_off_topic_and_prefers_faceless_mood() -> None:
    pool = [
        _alt("brush", "Macro view of a hairbrush"),
        _alt("fur", "Close-up of thick animal fur"),
        _alt("face", "young woman with braided hair", face=True),
        *[_alt(f"h{i}", f"close up of a person's hair {i}") for i in range(4)],
    ]
    hero, mood, options = unsplash.choose_images(pool, "salon")
    assert hero is not None and hero.id == "brush"
    assert "fur" not in {p.id for p in options}
    assert [p.id for p in mood] == ["h0", "h1", "h2", "h3"]


def test_salon_renders_seven_strips_from_one_image_and_three_narrow() -> None:
    pool = [_alt(f"p{i}", f"close up of a person's hair {i}") for i in range(6)]
    from app.demo_site import DemoImages
    hero, mood, options = unsplash.choose_images(pool, "salon")
    html = render_demo_html(
        template="salon", color_scheme="jarvi", business=BUSINESS, sender=SENDER,
        content=DemoStoredContent(**VALID, images=DemoImages(hero=hero, mood=mood, options=options)),
    )
    assert html.count('class="kaisla"') == 7
    # Sama kuva seitsemässä suikaleessa: selain lataa sen kerran
    assert html.count('<img src="https://images.unsplash.com/p0?') == 7
    assert html.count("<li><img") == 3


# --- Parturi: kulmakyltti ---

from app.demo_site import Kyltti, kyltti_split  # noqa: E402


@pytest.mark.parametrize("name,expected", [
    ("Kulmapää", ("Kulma", "pää")),                                   # yhdyssanan liitos
    ("Hiusateljee", ("Hius", "ateljee")),
    ("Herrasmiesten Parturi", ("Herrasmiesten", "Parturi")),           # sanan kohdalta
    ("Parturi-Kampaamo Taina Lantiainen", ("Parturi-Kampaamo", "Taina Lantiainen")),  # tasaisin jako
    ("Parturi Salo Oy", ("Parturi", "Salo")),                          # yritysmuoto pois
    ("Ässä", ("Ässä", "Parturi")),                                     # varaversio: <= 5 merkkiä
    ("Xyzabcdef", ("Xyzabcdef", "Parturi")),                           # varaversio: ei jakokohtaa
    ("Parturi", ("Parturi", "Barber")),                                # ei "Parturi Parturi"
])
def test_kyltti_split(name: str, expected: tuple[str, str]) -> None:
    assert kyltti_split(name) == Kyltti(*expected)


def test_kyltti_split_too_long_falls_back_to_plain_heading() -> None:
    assert kyltti_split("Parturi-Kampaamo Kauniaisten Hiuspiste Oy") is None


def test_kyltti_counts_have_css_rules() -> None:
    css = (ASSET_DIR / "barber" / "tyylit.css").read_text()
    for n in range(2, 17):
        assert f'[data-vaaka="{n}"]' in css and f'[data-pysty="{n}"]' in css


def _barber(name: str) -> str:
    business = DemoBusiness(name=name, city="Oulu", address="Esimerkkikatu 15, 90100 Oulu, Suomi",
                            phone="050 000 0000", maps_url="https://maps.google.com/?cid=1")
    return render_demo_html(template="barber", color_scheme="kyltti", business=business, sender=SENDER,
                            content=DemoStoredContent(**VALID))


def test_barber_renders_kyltti_with_counts_and_readable_name() -> None:
    html = _barber("Herrasmiesten Parturi")
    assert 'data-vaaka="13" data-pysty="7"' in html
    assert '<a class="logo" href="#sisalto">Herrasmiesten Parturi</a>' in html  # luettava nimi yläpalkissa
    assert 'class="seina seina-vaaka" aria-hidden="true"' in html
    assert "<h2 id=\"yhteys-otsikko\">Esimerkkikatu 15</h2>" in html


def test_barber_long_name_uses_plain_heading() -> None:
    html = _barber("Parturi-Kampaamo Kauniaisten Hiuspiste Oy")
    assert "kyltti-varaversio" in html and "data-vaaka" not in html


def test_barber_images_are_grayscale_by_css() -> None:
    assert "main img { filter: grayscale(1)" in (ASSET_DIR / "barber" / "tyylit.css").read_text()


@pytest.mark.parametrize("text", [
    "barber shaving a man's beard with a straight razor",
    "man getting a shave at the barbershop",
])
def test_blade_with_person_is_face_risk(text: str) -> None:
    assert unsplash.face_risk(text)


def test_blade_without_person_is_fine() -> None:
    assert not unsplash.face_risk("straight razor and comb on a wooden table")


def test_barber_queries_mix_interior_and_tools() -> None:
    assert unsplash.image_queries("barber_shop", "barber") == ["barbershop interior", "barber tools"]
    assert unsplash.uses_both_queries("barber")


# --- Tuotemerkit kuvissa, kampaamon lopputuloskuvat, palvelugrid ---

def test_blocked_photo_ids_never_chosen() -> None:
    pool = [_alt("WbEibGKHBMY", "stainless steel scissors and hair comb"), _alt("ok1", "barbershop chairs"),
            _alt("2y4qGxu-4Do", "a black case filled with lots of different items"), _alt("ok2", "scissors on a table")]
    hero, mood, options = unsplash.choose_images(pool, "barber")
    chosen = {p.id for p in [hero, *mood, *options] if p}
    assert not chosen & set(unsplash.BLOCKED_PHOTO_IDS)
    assert unsplash.mood_for(None, [pool[0], pool[1]], "barber") == [pool[1]]


def test_tool_closeups_are_last_resort() -> None:
    def parsed(pid: str, alt: str) -> unsplash.DemoPhoto:
        photo = unsplash._to_photo({
            "id": pid, "urls": {"raw": f"https://images.unsplash.com/{pid}"}, "alt_description": alt,
            "user": {"name": "N", "links": {"html": "https://unsplash.com/@n"}}, "links": {"download_location": "x"},
        })
        assert photo is not None
        return photo
    clipper = parsed("c", "a hair clipper on a wooden table")
    brush = parsed("b", "a close up of a table with a hair brush and a pair of scissors")
    chairs = parsed("k", "barbershop chairs and mirrors")
    scissors = parsed("s", "scissors and comb on a table")
    assert clipper.tool_closeup and brush.tool_closeup and not chairs.tool_closeup
    hero, mood, options = unsplash.choose_images([clipper, brush, chairs, scissors], "barber")
    assert hero is not None and hero.id == "k"
    assert [p.id for p in options][-2:] == ["c", "b"]


def test_salon_drops_frizz_and_ranks_non_hair_last() -> None:
    pool = [
        _alt("wave", "a close up of a wave"),
        _alt("frizz", "frizzy static hair close up"),
        _alt("gloss", "glossy brown hair on black background"),
        _alt("bun", "a close up of a woman's hair in a bun"),
        _alt("braid", "a braided hairstyle seen from behind"),
    ]
    hero, mood, options = unsplash.choose_images(pool, "salon")
    assert hero is not None and hero.id == "gloss"
    assert "frizz" not in {p.id for p in options}
    assert [p.id for p in mood] == ["bun", "braid", "wave"]


@pytest.mark.parametrize("count", [3, 4, 5, 6])
def test_salon_service_grid_has_count_class(count: int) -> None:
    services = [{"name": f"Palvelu {chr(65 + i)}", "description": "Kuvaus palvelusta tähän."} for i in range(count)]
    html = render_demo_html(template="salon", color_scheme="jarvi", business=BUSINESS, sender=SENDER,
                            content=DemoStoredContent(**{**VALID, "services": services}))
    assert f'class="palvelut n{count}"' in html
    css = (ASSET_DIR / "salon" / "tyylit.css").read_text()
    assert ".palvelut.n4 { grid-template-columns: repeat(2, minmax(0, 1fr));" in css


# --- Puhelinnäkymän kuvakaappaus ---

def test_screenshot_endpoint_returns_jpeg_and_caches(
    client_a: TestClient, cafe_demo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr("app.main._SCREENSHOT_CACHE", __import__("collections").OrderedDict())
    monkeypatch.setattr("app.main.screenshot_demo", lambda html: calls.append(html) or b"\xff\xd8jpeg")
    url = f"/leads/{cafe_demo['lead_id']}/demo/screenshot"
    res = client_a.get(url)
    assert res.status_code == 200 and res.headers["content-type"] == "image/jpeg"
    assert res.content == b"\xff\xd8jpeg"
    client_a.get(url)
    assert len(calls) == 1  # sama HTML -> välimuistista


def test_screenshot_without_playwright_is_501(
    client_a: TestClient, cafe_demo: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.demo_site import ScreenshotUnavailable

    def unavailable(html: str) -> bytes:
        raise ScreenshotUnavailable("Playwright not installed")

    monkeypatch.setattr("app.main._SCREENSHOT_CACHE", __import__("collections").OrderedDict())
    monkeypatch.setattr("app.main.screenshot_demo", unavailable)
    assert client_a.get(f"/leads/{cafe_demo['lead_id']}/demo/screenshot").status_code == 501


def test_screenshot_is_owner_only(client_b: TestClient, cafe_demo: dict[str, Any]) -> None:
    assert client_b.get(f"/leads/{cafe_demo['lead_id']}/demo/screenshot").status_code == 404


# --- Kyltin varaversion otsikon koko (live-demo: "Olarin Parturi-kampaamo Saloon lion") ---

from app.demo_site import longest_segment  # noqa: E402


@pytest.mark.parametrize("name,expected", [
    ("Olarin Parturi-kampaamo Saloon lion", 8),      # "Parturi-" / "kampaamo" / "Olarin"
    ("Parturi-Kampaamo Kauniaisten Hiuspiste Oy", 11),  # "Kauniaisten"
    ("Ab", 2),
    ("Ylivoimaisenpitkäsanainenparturiliike Oy", 30),  # katto 30
])
def test_longest_segment(name: str, expected: int) -> None:
    assert longest_segment(name) == expected


def test_fallback_heading_sized_by_longest_segment() -> None:
    html = _barber("Olarin Parturi-kampaamo Saloon lion")
    assert 'class="nimi" data-pisin="8"' in html
    css = (ASSET_DIR / "barber" / "tyylit.css").read_text()
    assert all(f'[data-pisin="{n}"] {{ --pisin: {n}; }}' in css for n in range(2, 31))


@pytest.mark.parametrize("template", V2_TEMPLATES)
def test_ai_headings_carry_longest_word_for_css_sizing(template: str) -> None:
    content = DemoStoredContent(**{**VALID, "hero_title": "Kampaamopalvelut Kauniaisissa",
                                   "about_title": "Parturi- ja kampaamopalvelut"})
    html = render_demo_html(template=template, color_scheme=next(iter(TEMPLATES[template].schemes)),
                            business=BUSINESS, sender=SENDER, content=content)
    assert '<h1 data-pisin="16">Kampaamopalvelut Kauniaisissa</h1>' in html
    assert 'data-pisin="16">Parturi- ja kampaamopalvelut</h2>' in html
    css = (ASSET_DIR / template / "tyylit.css").read_text()
    assert "container-type: inline-size" in css and "var(--mahtuu" in css


def _render_with_booking(template: str, booking_url: Optional[str]) -> str:
    business = DemoBusiness(
        name="Salonki Lumo", city="Espoo", address="Esimerkkikatu 4, 02100 Espoo, Suomi",
        phone="050 000 0000", maps_url="https://maps.google.com/?cid=1", booking_url=booking_url,
    )
    content = DemoStoredContent(**VALID, price_note=price_note_for(template))
    return render_demo_html(template=template, color_scheme=next(iter(TEMPLATES[template].schemes)),
                            content=content, business=business, sender=SENDER)


@pytest.mark.parametrize("template", ["salon", "barber"])
def test_book_button_links_to_booking_platform(template: str) -> None:
    html = _render_with_booking(template, "https://timma.fi/salonki-lumo")
    assert re.search(r'<a class="nappi[^"]*" href="https://timma\.fi/salonki-lumo" rel="noopener noreferrer">Varaa aika</a>', html)
    assert "<iframe" not in html


@pytest.mark.parametrize("template", ["salon", "barber"])
def test_book_button_without_booking_url_is_phone_link(template: str) -> None:
    html = _render_with_booking(template, None)
    assert "timma" not in html and "verkossa" not in html
    assert re.search(r'href="tel:\+358500000000">(Varaa aika|Soita 050 000 0000)</a>', html)
    if template == "salon":
        assert '<a class="nappi nappi-pieni" href="tel:+358500000000">Varaa aika</a>' in html


def test_price_note_with_booking_platform_says_online() -> None:
    assert price_note_for("salon", has_booking=True) == "Hinnat näette ajanvarauksesta."
    assert price_note_for("salon") == "Hinnat ja ajanvaraus puhelimitse."
    # Vain hinnaton oletusteksti vaihtuu; kahvilan ja hinnallinen teksti ennallaan
    assert price_note_for("salon", has_prices=True, has_booking=True) == price_note_for("salon", has_prices=True)
    assert price_note_for("cafe", has_booking=True) == price_note_for("cafe")


def test_booking_lead_demo_gets_online_price_note_and_follows_template(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead = make_lead(
        name="Kampaamo Lumo", phone="040 000 0000", primary_type="hair_salon", website="https://timma.fi/lumo",
        website_status="NO WEBSITE", website_issue="booking platform only",
    )
    fake_openai.reply = json.dumps(VALID)
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={"template": "salon"}).json()
    assert demo["content"]["price_note"] == "Hinnat näette ajanvarauksesta."
    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "cafe"}).json()
    assert res["content"]["price_note"] == price_note_for("cafe")
    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"template": "barber"}).json()
    assert res["content"]["price_note"] == "Hinnat näette ajanvarauksesta."


@pytest.mark.parametrize("template", ["salon", "barber"])
def test_services_line_with_booking_platform(template: str) -> None:
    business = DemoBusiness(
        name="Salonki Lumo", city="Espoo", address="Esimerkkikatu 4, 02100 Espoo, Suomi",
        phone="050 000 0000", maps_url=None, booking_url="https://timma.fi/salonki-lumo",
    )
    content = DemoStoredContent(**VALID, price_note=price_note_for(template, has_booking=True))
    html = render_demo_html(template=template, color_scheme=next(iter(TEMPLATES[template].schemes)),
                            content=content, business=business, sender=SENDER)
    assert '<p class="huom">Varatkaa aika verkossa tai puhelimitse. Hinnat näette ajanvarauksesta.</p>' in html
    assert "Varatkaa aika puhelimitse." not in html


@pytest.mark.parametrize("template", ["salon", "barber"])
def test_services_line_without_booking_is_unchanged(template: str) -> None:
    html = _render_with_booking(template, None)
    assert '<p class="huom">Varatkaa aika puhelimitse. Hinnat ja ajanvaraus puhelimitse.</p>' in html


def test_cafe_ignores_booking_url_in_services_line() -> None:
    html = _render_with_booking("cafe", "https://timma.fi/kahvila")
    assert TEMPLATES["cafe"].services_lead in html and "verkossa tai puhelimitse" not in html

