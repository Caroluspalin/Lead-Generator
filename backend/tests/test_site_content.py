"""Nykyisen sivun sisältö demoon: skannaus (robots.txt, viive, max 3 alasivua), tarkistus, hinnat ja sähköposti."""
import json
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.demo_site import (
    SITE_PRICES_NOTE,
    TEMPLATES,
    DemoAIService,
    DemoBusiness,
    DemoSender,
    DemoService,
    DemoStoredContent,
    attach_site_prices,
    build_demo_prompt,
    price_note_for,
    render_demo_html,
)
from app.main import DEMO_LINK_PARAGRAPH, DEMO_LINK_PARAGRAPH_SITE, build_demo_email_body
from app.models import Lead, SenderProfile
from app.utils import site_content
from app.utils.site_content import (
    REQUEST_DELAY_SECONDS,
    SiteFacts,
    SitePage,
    SiteScan,
    SiteService,
    scan_site,
    should_scan,
    verify_site_facts,
)
from tests.conftest import FakeOpenAI
from tests.test_demo_publish import CONFIG, FakeStore
from tests.test_demo_site import VALID

SITE = "https://parturi-esimerkki.fi"


class _Resp:
    def __init__(self, url: str, status: int, text: str, content_type: str = "text/html; charset=utf-8",
                 location: Optional[str] = None) -> None:
        self.url = url
        self.status_code = status
        self.text = text
        self.headers = {"Content-Type": content_type, **({"Location": location} if location else {})}


def _html(body: str) -> str:
    return f"<html><head><title>T</title></head><body>{body}</body></html>"


HOME = _html("""
<nav><a href="/">Etusivu</a></nav>
<main>
  <h1>Parturi Esimerkki</h1>
  <p>Olemme parturi Espoon Tapiolassa. Leikkaamme miesten ja lasten hiukset ilman ajanvarausta.</p>
  <img src="https://parturi-esimerkki.fi/kuvat/liike.jpg" alt="Liikkeen julkisivu">
  <a href="/palvelut">Palvelut</a>
  <a href="/hinnasto">Hinnasto</a>
  <a href="/meista">Meistä</a>
  <a href="/palvelut/parta">Partapalvelut</a>
  <a href="/galleria">Galleria</a>
  <a href="/yhteystiedot">Yhteystiedot</a>
  <a href="https://toinen-sivusto.fi/palvelut">Kumppanin palvelut</a>
  <a href="/hinnasto.pdf">Hinnasto PDF</a>
</main>
""")
SERVICES = _html("""
<h1>Palvelut</h1>
<p>Hiustenleikkaus: perinteinen leikkaus koneella tai saksilla.</p>
<p>Parranajo: kuumapyyhe ja partaveitsi.</p>
<p>Lasten leikkaus alle 12-vuotiaille.</p>
<picture><source srcset="https://parturi-esimerkki.fi/kuvat/tuoli.webp"></picture>
""")
PRICES = _html("""
<h1>Hinnasto</h1>
<table>
<tr><td>Hiustenleikkaus</td><td>32 €</td></tr>
<tr><td>Parranajo</td><td>alk. 25 €</td></tr>
<tr><td>Lasten leikkaus</td><td>22 €</td></tr>
</table>
""")
ABOUT = _html("""
<h1>Meistä</h1>
<p>Parturi Esimerkki on palvellut Tapiolan asukkaita pitkään. Meillä leikataan miesten ja lasten hiukset
ilman ajanvarausta, ja parranajo tehdään perinteisesti kuumapyyhkeellä.</p>
""")


class FakeSite:
    """Mockattu requests.get: osoite -> vastaus. Kirjaa haetut osoitteet."""

    def __init__(self, pages: dict[str, _Resp]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str, **_kwargs: Any) -> _Resp:
        self.requested.append(url)
        resp = self.pages.get(url)
        if resp is None:
            return _Resp(url, 404, "<html><body>Ei löydy</body></html>")
        return resp


def _site(robots: Optional[_Resp] = None, **overrides: _Resp) -> dict[str, _Resp]:
    pages = {
        f"{SITE}/robots.txt": robots or _Resp(f"{SITE}/robots.txt", 200, "User-agent: *\nAllow: /\n", "text/plain"),
        SITE: _Resp(SITE, 200, HOME),
        f"{SITE}/palvelut": _Resp(f"{SITE}/palvelut", 200, SERVICES),
        f"{SITE}/hinnasto": _Resp(f"{SITE}/hinnasto", 200, PRICES),
        f"{SITE}/meista": _Resp(f"{SITE}/meista", 200, ABOUT),
    }
    pages.update(overrides)
    return pages


# Testien kuvitteelliset nimet "resolvoituvat" julkiseen osoitteeseen (ei oikeaa DNS-kyselyä)
PRIVATE_HOSTS = {"sisainen.example": "10.0.0.5", "metadata.example": "169.254.169.254", "localhost": "127.0.0.1"}


def _fake_resolve(host: str) -> list[str]:
    return [PRIVATE_HOSTS.get(host, "93.184.216.34")]


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(pages: dict[str, _Resp]) -> FakeSite:
        fake = FakeSite(pages)
        monkeypatch.setattr("app.utils.site_content.requests.get", fake.get)
        monkeypatch.setattr("app.utils.site_content._resolve", _fake_resolve)
        return fake

    return _install


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr("app.utils.site_content.time.sleep", recorded.append)
    return recorded


# --- Mitä skannataan ---

def test_should_scan_only_partly_working_sites() -> None:
    assert should_scan(SITE, "NOT MOBILE", "no viewport meta")
    assert should_scan(SITE, "INSECURE", "SSL certificate expired")
    assert should_scan(SITE, "BROKEN WEBSITE", "HTTP 500")
    assert not should_scan(SITE, "BROKEN WEBSITE", "parked domain")
    assert not should_scan(SITE, "BROKEN WEBSITE", "DNS not resolving")
    assert not should_scan(SITE, "WEBSITE OK", None)
    assert not should_scan(None, "NOT MOBILE", None)


def test_scan_reads_home_and_at_most_three_subpages(site: Any, sleeps: list[float]) -> None:
    fake = site(_site())
    scan = scan_site(SITE)
    assert scan is not None
    assert [p.kind for p in scan.pages] == ["home", "prices", "services", "about"]
    assert fake.requested == [
        f"{SITE}/robots.txt", SITE, f"{SITE}/hinnasto", f"{SITE}/palvelut", f"{SITE}/meista",
    ]
    # Ei toista palvelusivua, galleriaa, yhteystietoja, ulkoista sivustoa eikä PDF:ää
    assert not any(u.endswith(("/palvelut/parta", "/galleria", ".pdf")) or "toinen-sivusto" in u for u in fake.requested)


def test_scan_never_extracts_images(site: Any, sleeps: list[float]) -> None:
    site(_site())
    scan = scan_site(SITE)
    assert scan is not None
    text = "\n".join(p.text for p in scan.pages)
    assert ".jpg" not in text and ".webp" not in text and "julkisivu" not in text


def test_waits_between_requests(site: Any, sleeps: list[float]) -> None:
    fake = site(_site())
    scan_site(SITE)
    # Jokaista pyyntöä ennen ensimmäisen jälkeen odotetaan
    assert len(sleeps) == len(fake.requested) - 1
    assert all(0 < s <= REQUEST_DELAY_SECONDS for s in sleeps)


def test_crawl_delay_from_robots_is_respected(site: Any, sleeps: list[float]) -> None:
    robots = _Resp(f"{SITE}/robots.txt", 200, "User-agent: *\nCrawl-delay: 3\n", "text/plain")
    site(_site(robots=robots))
    scan_site(SITE)
    assert sleeps and all(2.5 < s <= 3 for s in sleeps)


def test_robots_disallowed_subpage_is_not_fetched(site: Any, sleeps: list[float]) -> None:
    robots = _Resp(f"{SITE}/robots.txt", 200, "User-agent: *\nDisallow: /hinnasto\n", "text/plain")
    fake = site(_site(robots=robots))
    scan = scan_site(SITE)
    assert scan is not None
    assert f"{SITE}/hinnasto" not in fake.requested
    assert scan.blocked == [f"{SITE}/hinnasto"]
    assert [p.kind for p in scan.pages] == ["home", "services", "about"]


def test_robots_disallowing_everything_fetches_nothing(site: Any, sleeps: list[float]) -> None:
    robots = _Resp(f"{SITE}/robots.txt", 200, "User-agent: AgencyHunter\nDisallow: /\n", "text/plain")
    fake = site(_site(robots=robots))
    scan = scan_site(SITE)
    assert scan is not None and scan.pages == []
    assert fake.requested == [f"{SITE}/robots.txt"]


@pytest.mark.parametrize("status", [500, 503, 401, 403])
def test_unreadable_robots_means_no_fetching(site: Any, sleeps: list[float], status: int) -> None:
    fake = site(_site(robots=_Resp(f"{SITE}/robots.txt", status, "virhe", "text/plain")))
    scan = scan_site(SITE)
    assert scan is not None and scan.pages == []
    assert fake.requested == [f"{SITE}/robots.txt"]


def test_missing_robots_allows_everything(site: Any, sleeps: list[float]) -> None:
    fake = site(_site(robots=_Resp(f"{SITE}/robots.txt", 404, "", "text/html")))
    scan = scan_site(SITE)
    assert scan is not None and len(scan.pages) == 4
    assert len(fake.requested) == 5


def test_broken_site_with_content_is_used(site: Any, sleeps: list[float]) -> None:
    site(_site(**{SITE: _Resp(SITE, 500, HOME)}))
    scan = scan_site(SITE)
    assert scan is not None
    assert scan.pages[0].kind == "home"
    assert "Tapiolassa" in (scan.homepage_text or "")


def test_unreachable_home_returns_none(site: Any, sleeps: list[float]) -> None:
    site(_site(**{SITE: _Resp(SITE, 200, "%PDF", "application/pdf")}))
    assert scan_site(SITE) is None


# --- AI:n vastauksen tarkistus sivuja vasten ---

def _scan() -> SiteScan:
    return SiteScan(pages=[
        SitePage("home", SITE, "Parturi Esimerkki\nOlemme parturi Espoon Tapiolassa. Leikkaamme miesten ja lasten hiukset."),
        SitePage("prices", f"{SITE}/hinnasto", "Hinnasto\nHiustenleikkaus\n32 €\nParranajo\nalk. 25 €\nLasten leikkaus 22 e"),
        SitePage("services", f"{SITE}/palvelut", "Palvelut\nKoneajo nopeasti ja siististi.\nParran muotoilu."),
    ], blocked=[])


def test_verify_keeps_prices_next_to_service_name() -> None:
    raw = SiteFacts(services=[
        SiteService(name="Hiustenleikkaus", price="32 €"),
        SiteService(name="Parranajo", price="alk. 25 €"),
        SiteService(name="Lasten leikkaus", price="22 €"),
    ])
    facts = verify_site_facts(raw, _scan())
    assert [(s.name, s.price) for s in facts.services] == [
        ("Hiustenleikkaus", "32 €"), ("Parranajo", "alk. 25 €"), ("Lasten leikkaus", "22 €"),
    ]


def test_verify_drops_invented_prices_and_services() -> None:
    raw = SiteFacts(services=[
        SiteService(name="Hiustenleikkaus", price="35 €"),  # sivulla 32 €
        SiteService(name="Koneajo", price="20 €"),  # ei hintaa sivulla
        SiteService(name="Kestovärjäys", price="60 €"),  # ei koko palvelua
        SiteService(name="Parran muotoilu", price=None),
    ])
    facts = verify_site_facts(raw, _scan())
    assert [(s.name, s.price) for s in facts.services] == [
        ("Hiustenleikkaus", None), ("Koneajo", None), ("Parran muotoilu", None),
    ]
    assert not facts.has_prices


def test_verify_drops_price_from_another_page() -> None:
    scan = SiteScan(pages=[
        SitePage("services", SITE, "Hiustenleikkaus saksilla tai koneella. " + "Lisätietoa palveluista. " * 20),
        SitePage("prices", f"{SITE}/hinnasto", "Hinnasto\nParranajo 32 €"),
    ], blocked=[])
    facts = verify_site_facts(SiteFacts(services=[SiteService(name="Hiustenleikkaus", price="32 €")]), scan)
    assert facts.services[0].price is None


def test_verify_drops_about_not_from_site() -> None:
    kept = verify_site_facts(SiteFacts(about="Olemme parturi Espoon Tapiolassa. Leikkaamme miesten ja lasten hiukset."), _scan())
    assert kept.about
    invented = verify_site_facts(SiteFacts(about="Perheyritys vuodesta 1985, palkittu parturi ja kampaamo Helsingissä."), _scan())
    assert invented.about is None
    assert invented.pages == [SITE, f"{SITE}/hinnasto", f"{SITE}/palvelut"]


# --- Hinnat demoon ---

FACTS = SiteFacts(services=[
    SiteService(name="Hiustenleikkaus", price="32 €"),
    SiteService(name="Värjäys", price="alk. 60 €"),
    SiteService(name="Kampaukset"),
], about="Leikkaamme naisten, miesten ja lasten hiukset.")


def _ai_services() -> list[DemoAIService]:
    return [DemoAIService(**s) for s in VALID["services"]]


def test_attach_prices_only_from_site_facts() -> None:
    services = attach_site_prices(_ai_services(), FACTS)
    assert [(s.name, s.price) for s in services] == [
        ("Hiustenleikkaus", "32 €"), ("Värjäys", "alk. 60 €"), ("Kampaukset", None),
    ]
    assert all(s.price is None for s in attach_site_prices(_ai_services(), None))
    assert all(s.price is None for s in attach_site_prices(_ai_services(), SiteFacts(services=[SiteService(name="Värjäys")])))


def test_prompt_lists_site_services_but_never_prices() -> None:
    prompt = build_demo_prompt(name="Parturi", city="Espoo", primary_type="barber_shop", website_context=None, site_facts=FACTS)
    assert "- Hiustenleikkaus" in prompt and "TÄSMÄLLEEN" in prompt
    assert "€" not in prompt and "32" not in prompt
    assert "Leikkaamme naisten" in prompt


BUSINESS = DemoBusiness(name="Parturi Esimerkki", city="Espoo", address="Katu 1, 02100 Espoo, Suomi", phone="040 000 0000",
                        maps_url="https://maps.google.com/?cid=1")
SENDER = DemoSender(name="Carolus Palin", company_name="Palin Web", phone="040 111 2222", website="https://palinweb.fi")


def _render(template: str, services: list[DemoService]) -> str:
    has_prices = any(s.price for s in services)
    content = DemoStoredContent(**{**VALID, "services": [s.model_dump() for s in services]},
                                price_note=price_note_for(template, has_prices))
    return render_demo_html(template=template, color_scheme=next(iter(TEMPLATES[template].schemes)),
                            content=content, business=BUSINESS, sender=SENDER)


@pytest.mark.parametrize("template", list(TEMPLATES))
def test_every_template_shows_site_prices_with_note(template: str) -> None:
    html = _render(template, attach_site_prices(_ai_services(), FACTS))
    assert "32 €" in html and "alk. 60 €" in html
    assert SITE_PRICES_NOTE in html
    assert "Hinnat ja ajanvaraus puhelimitse" not in html


@pytest.mark.parametrize("template", list(TEMPLATES))
def test_no_prices_and_no_note_without_site_prices(template: str) -> None:
    html = _render(template, attach_site_prices(_ai_services(), None))
    assert "€" not in html
    assert SITE_PRICES_NOTE not in html


def test_price_note_with_prices_does_not_repeat_services_lead() -> None:
    for name, tpl in TEMPLATES.items():
        assert price_note_for(name, True) != tpl.services_lead
        assert "hinn" not in price_note_for(name, True).lower()


# --- Sähköposti ---

def _profile() -> SenderProfile:
    return SenderProfile(user_id="u", name="Carolus", short_intro="teen nettisivuja", phone="040 1")


def test_email_mentions_current_information_only_for_site_based_demo() -> None:
    url = "https://demo.example/parturi"
    site_body = build_demo_email_body("Kappale yksi.\n\nKappale kaksi.", _profile(), url, site_based=True)
    assert DEMO_LINK_PARAGRAPH_SITE.format(url=url) in site_body
    assert "nykyisten tietojenne pohjalta" in site_body
    plain = build_demo_email_body("Kappale yksi.\n\nKappale kaksi.", _profile(), url)
    assert DEMO_LINK_PARAGRAPH.format(url=url) in plain
    assert "nykyisten tietojenne" not in plain


# --- Endpointit: demo, PATCH ja sähköposti mockatulla sivulla ---

AI_FACTS = {
    "services": [
        {"name": "Hiustenleikkaus", "price": "32 €"},
        {"name": "Parranajo", "price": "alk. 25 €"},
        {"name": "Lasten leikkaus", "price": "99 €"},  # keksitty: sivulla 22 €
    ],
    "about": "Meillä leikataan miesten ja lasten hiukset ilman ajanvarausta.",
}
AI_DEMO = {
    **VALID,
    "about": "Leikkaamme miesten ja lasten hiukset ilman ajanvarausta.",
    "services": [
        {"name": "Hiustenleikkaus", "description": "Leikkaus koneella tai saksilla toiveiden mukaan."},
        {"name": "Parranajo", "description": "Kuumapyyhe ja partaveitsi rauhassa."},
        {"name": "Lasten leikkaus", "description": "Leikkaus alle kouluikäisille ja koululaisille."},
    ],
}


@pytest.fixture
def site_lead(make_lead: Any) -> dict[str, Any]:
    return make_lead(name="Parturi Esimerkki", city="Espoo", website=SITE, website_status="NOT MOBILE",
                     website_issue="no viewport meta", primary_type="barber_shop", phone="040 000 0000")


@pytest.fixture
def site_demo(client_a: TestClient, site_lead: dict[str, Any], fake_openai: type[FakeOpenAI],
              sender_profile: dict[str, Any], site: Any, sleeps: list[float]) -> dict[str, Any]:
    site(_site())
    fake_openai.replies = [json.dumps(AI_FACTS), json.dumps(AI_DEMO)]
    res = client_a.post(f"/leads/{site_lead['id']}/demo", json={})
    assert res.status_code == 200, res.text
    return res.json()


def test_demo_uses_site_services_and_verified_prices(
    site_demo: dict[str, Any], fake_openai: type[FakeOpenAI], session: Session, site_lead: dict[str, Any]
) -> None:
    prices = {s["name"]: s["price"] for s in site_demo["content"]["services"]}
    assert prices == {"Hiustenleikkaus": "32 €", "Parranajo": "alk. 25 €", "Lasten leikkaus": None}
    assert site_demo["content"]["site_based"] is True
    assert site_demo["content"]["price_note"] == price_note_for("barber", True)

    # 1. kutsu: rakenteistus sivujen tekstistä, 2. kutsu: demo, jonka promptissa palvelut ilman hintoja
    assert "=== SIVU (prices)" in fake_openai.calls[0]["messages"][1]["content"]
    demo_prompt = fake_openai.calls[1]["messages"][1]["content"]
    assert "- Hiustenleikkaus" in demo_prompt and "32 €" not in demo_prompt

    lead = session.get(Lead, site_lead["id"])
    assert lead is not None and lead.website_facts and lead.website_facts_at
    assert "Tapiolassa" in (lead.website_context or "")


def test_demo_html_has_prices_but_no_site_images(client_a: TestClient, site_demo: dict[str, Any]) -> None:
    html = client_a.get(f"/demo/{site_demo['public_path']}").text
    assert "32 €" in html and SITE_PRICES_NOTE in html
    assert "parturi-esimerkki.fi/kuvat" not in html


def test_site_is_scanned_once_per_lead(
    client_a: TestClient, site_demo: dict[str, Any], fake_openai: type[FakeOpenAI], site_lead: dict[str, Any]
) -> None:
    fake_openai.replies = [json.dumps(AI_DEMO)]
    calls_before = len(fake_openai.calls)
    assert client_a.post(f"/leads/{site_lead['id']}/demo", json={}).status_code == 200
    assert len(fake_openai.calls) == calls_before + 1  # vain demo, ei uutta rakenteistusta


def test_patch_can_remove_price_but_not_invent_one(client_a: TestClient, site_demo: dict[str, Any]) -> None:
    content = {k: v for k, v in site_demo["content"].items() if k not in ("opening_hours", "opening_periods", "images", "site_based", "timma")}
    removed = {**content, "services": [{**s, "price": None} for s in content["services"]]}
    res = client_a.patch(f"/leads/{site_demo['lead_id']}/demo", json={"content": removed})
    assert res.status_code == 200
    assert SITE_PRICES_NOTE not in client_a.get(f"/demo/{site_demo['public_path']}").text
    assert res.json()["content"]["price_note"] == price_note_for("barber")
    assert res.json()["content"]["site_based"] is True

    invented = {**content, "services": [{**s, "price": "10 €"} for s in content["services"]]}
    assert client_a.patch(f"/leads/{site_demo['lead_id']}/demo", json={"content": invented}).status_code == 422


def test_demo_without_site_has_no_prices(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead = make_lead(name="Parturi Ilman", city="Espoo", website_status="NO WEBSITE", primary_type="barber_shop")
    fake_openai.reply = json.dumps(VALID)
    demo = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    assert all(s["price"] is None for s in demo["content"]["services"])
    assert demo["content"]["site_based"] is False
    assert len(fake_openai.calls) == 1


def test_robots_blocked_site_gives_generic_demo(
    client_a: TestClient, site_lead: dict[str, Any], fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    site: Any, sleeps: list[float],
) -> None:
    robots = _Resp(f"{SITE}/robots.txt", 200, "User-agent: *\nDisallow: /\n", "text/plain")
    fake = site(_site(robots=robots))
    fake_openai.reply = json.dumps(VALID)
    demo = client_a.post(f"/leads/{site_lead['id']}/demo", json={}).json()
    assert fake.requested == [f"{SITE}/robots.txt"]
    assert demo["content"]["site_based"] is False
    assert len(fake_openai.calls) == 1  # ei rakenteistusta


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: fake)
    return fake


def test_demo_email_says_draft_is_based_on_current_information(
    client_a: TestClient, site_demo: dict[str, Any], store: FakeStore, fake_openai: type[FakeOpenAI]
) -> None:
    assert client_a.post(f"/leads/{site_demo['lead_id']}/demo/publish").status_code == 200
    fake_openai.reply = "Hei, olen Carolus ja teen nettisivuja.\n\nSivunne ei toimi puhelimella hyvin."
    body = client_a.post(f"/leads/{site_demo['lead_id']}/generate-email", json={"require_demo_link": True}).json()["body"]
    assert "Tein luonnoksen nykyisten tietojenne pohjalta" in body


def test_email_deep_scan_for_partial_site_respects_robots(
    client_a: TestClient, site_lead: dict[str, Any], fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    site: Any, sleeps: list[float], monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _old_scraper(_url: str) -> str:
        raise AssertionError("vanhaa etusivun skraapperia ei käytetä osittain toimivalle sivulle")

    monkeypatch.setattr("app.main.scrape_website_text", _old_scraper)
    robots = _Resp(f"{SITE}/robots.txt", 200, "User-agent: *\nDisallow: /\n", "text/plain")
    fake = site(_site(robots=robots))
    assert client_a.post(f"/leads/{site_lead['id']}/generate-email", json={}).status_code == 200
    assert fake.requested == [f"{SITE}/robots.txt"]
    assert site_content.USER_AGENT in site_content.HEADERS["User-Agent"]


# --- SSRF-suoja: vain julkiset osoitteet, myös uudelleenohjauksissa ---

@pytest.mark.parametrize("url", [
    "http://localhost/", "http://127.0.0.1/", "http://10.0.0.1/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://sisainen.example/",
    "http://metadata.example/", "https://parturi-esimerkki.fi:8080/", "ftp://parturi-esimerkki.fi/",
    "file:///etc/passwd",
])
def test_non_public_urls_are_rejected(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.site_content._resolve", _fake_resolve)
    assert not site_content.is_public_url(url)


def test_public_url_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.utils.site_content._resolve", _fake_resolve)
    assert site_content.is_public_url(SITE)
    assert site_content.is_public_url("http://parturi-esimerkki.fi:80/palvelut")


def test_internal_site_is_never_requested(site: Any, sleeps: list[float]) -> None:
    fake = site({})
    assert scan_site("http://metadata.example/latest/meta-data/") is None
    assert fake.requested == []


def test_redirect_to_internal_address_is_not_followed(site: Any, sleeps: list[float]) -> None:
    fake = site(_site(**{SITE: _Resp(SITE, 302, "", location="http://169.254.169.254/latest/meta-data/")}))
    assert scan_site(SITE) is None
    assert not any("169.254" in u for u in fake.requested)


def test_public_redirect_is_followed(site: Any, sleeps: list[float]) -> None:
    target = "https://www.parturi-esimerkki.fi/"
    pages = _site(**{SITE: _Resp(SITE, 301, "", location=target)})
    pages[target] = _Resp(target, 200, HOME)
    fake = site(pages)
    scan = scan_site(SITE)
    assert scan is not None and scan.pages[0].url == target
    assert target in fake.requested


def test_demo_for_lead_with_internal_website_does_not_fetch_it(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    site: Any, sleeps: list[float], session: Session,
) -> None:
    fake = site({})
    # BROKEN (HTTP 500): skannataan, mutta sähköpostihaku (contact_finder) ei käynnisty taustalla
    lead = make_lead(name="Parturi Sisä", website="http://169.254.169.254/latest/meta-data/",
                     website_status="BROKEN WEBSITE", website_issue="HTTP 500", primary_type="barber_shop")
    fake_openai.reply = json.dumps(VALID)
    assert client_a.post(f"/leads/{lead['id']}/demo", json={}).status_code == 200
    assert fake.requested == []
    db_lead = session.get(Lead, lead["id"])
    assert db_lead is not None and db_lead.website_context is None
