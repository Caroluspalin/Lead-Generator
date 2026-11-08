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
    blocks = dict(re.findall(r'(:root|\[data-paletti="[a-z]+"\])\s*\{([^}]*)\}', css))
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
    assert "data-tanaan" in html and "data-tila" in html


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
    edited = {k: v for k, v in res["content"].items() if k not in ("opening_hours", "opening_periods", "images")}
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
