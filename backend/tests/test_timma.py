import json
import asyncio
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.utils import timma
from app.utils.timma import TimmaFetchError, fetch_timma, parse_timma, timma_slug

FIXTURE = Path(__file__).parent / "fixtures" / "timma_rmak.json"
RMAK_URL = "https://timma.fi/yritys/scissor-room-matinkyla?landingPage=parturi-espoo"


def rmak_payload() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


class FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b"", content_type: str = "application/json; charset=utf-8") -> None:
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeTimma:
    """requests.get-korvaaja: vastaukset jonosta, oletuksena tallennettu R-Makin vastaus."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.queue: list[FakeResponse] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.queue.pop(0) if self.queue else FakeResponse(body=FIXTURE.read_bytes())


@pytest.fixture
def fake_get(monkeypatch: pytest.MonkeyPatch) -> FakeTimma:
    fake = FakeTimma()
    monkeypatch.setattr("app.utils.timma.requests.get", fake.get)
    return fake


# --- Osoitteen tarkistus ---

@pytest.mark.parametrize("url,slug", [
    ("https://timma.fi/yritys/natawat", "natawat"),
    ("https://timma.fi/yritys/natawat/", "natawat"),
    (RMAK_URL, "scissor-room-matinkyla"),
])
def test_timma_slug_accepts_business_pages(url: str, slug: str) -> None:
    assert timma_slug(url) == slug


@pytest.mark.parametrize("url", [
    None,
    "",
    "http://timma.fi/yritys/natawat",  # vain https
    "https://www.timma.fi/yritys/natawat",  # vain täsmälleen timma.fi
    "https://timma.fi/pro/book-demo/642fff026759411f4a6cf069",  # markkinointisivu
    "https://timma.fi/yritys/",
    "https://timma.fi/yritys/natawat/varaa",
    "https://timma.fi/yritys/Natawat",
    "https://timma.fi/yritys/..%2Fapi",
    "https://timma.fi:8443/yritys/natawat",
    "https://timma.fi@evil.example/yritys/natawat",
    "https://timma.fi.evil.example/yritys/natawat",
    "https://evil.example/yritys/natawat",
    "timma.fi/yritys/natawat",
])
def test_timma_slug_rejects_everything_else(url: str | None) -> None:
    assert timma_slug(url) is None


# --- Jäsennin (tallennettu R-Makin vastaus) ---

def test_parse_rmak_fixture() -> None:
    snapshot = parse_timma(rmak_payload(), "scissor-room-matinkyla")
    assert snapshot.status == "ok"
    data = snapshot.data
    assert data is not None
    assert data.name == "R-Mak Barbershop"
    assert data.address == "Pyyntitie 1 A, 02230 Espoo"
    assert data.district == "Matinkylä"
    assert data.booking_url == "https://timma.fi/yritys/scissor-room-matinkyla"
    # Timman sivu näyttää "5 (262)": rating = [keskiarvo * 10, määrä]
    assert (data.rating_avg, data.rating_count) == (5.0, 262)
    assert len(data.services) == 12
    assert [c for c in dict.fromkeys(s.category for s in data.services)] == [
        "Leikkaukset", "Parta", "Muut hiuspalvelut", "Ihokarvojen poisto", "Combo",
    ]
    cut = next(s for s in data.services if s.name == "Parturileikkaus")
    assert (cut.price_cents, cut.duration_min, cut.from_price) == (2500, 30, False)
    assert cut.description == "Lyhyiden hiusten leikkaus tai siistiminen."
    assert len(data.images) == 2
    assert all(u.startswith("https://scaled-images.timma.fi/") for u in data.images)


def test_parse_does_not_keep_people_reviews_or_email() -> None:
    payload = rmak_payload()
    payload["users"] = [{"name": "Työntekijä Esimerkki", "imageUrl": "https://scaled-images.timma.fi/u.jpg"}]
    payload["email"] = "omistaja@example.com"
    payload["ratings"] = [{"comment": "Hyvä", "name": "Arvostelija"}]
    dumped = parse_timma(payload, "x").model_dump_json()
    for secret in ("Työntekijä", "omistaja@example.com", "Arvostelija", "u.jpg", "VIP Haircut"):
        assert secret not in dumped


def test_show_prices_false_hides_prices() -> None:
    payload = rmak_payload()
    payload["publicSettings"]["showPrices"] = False
    data = parse_timma(payload, "x").data
    assert data is not None and not data.show_prices
    assert all(s.price_cents is None and not s.from_price for s in data.services)


@pytest.mark.parametrize("flag", ["hideFromMarketplace", "noOnlineBookingIndexing"])
def test_hidden_business_is_not_used(flag: str) -> None:
    payload = rmak_payload()
    payload[flag] = True
    snapshot = parse_timma(payload, "x")
    assert snapshot.status == "hidden" and snapshot.data is None


def test_not_for_sale_services_and_foreign_images_skipped() -> None:
    payload = rmak_payload()
    payload["subCategories"][0]["services"][0]["forSaleWeb"] = False
    payload["images"].append({"url": "https://evil.example/kuva.jpg"})
    data = parse_timma(payload, "x").data
    assert data is not None
    assert len(data.services) == 11
    assert len(data.images) == 2


def test_rating_without_reviews_is_none() -> None:
    payload = rmak_payload()
    payload["rating"] = [0, 0]
    data = parse_timma(payload, "x").data
    assert data is not None and data.rating_avg is None and data.rating_count == 0


@pytest.mark.parametrize("mutate", [
    lambda p: p.pop("subCategories"),
    lambda p: p.__setitem__("subCategories", [{"name": "x", "items": []}]),
    lambda p: p.pop("name"),
])
def test_changed_structure_raises(mutate: Any) -> None:
    payload = rmak_payload()
    mutate(payload)
    with pytest.raises(TimmaFetchError):
        parse_timma(payload, "x")


# --- Haku ---

def test_fetch_uses_fixed_api_url_without_redirects(fake_get: FakeTimma) -> None:
    snapshot = fetch_timma("scissor-room-matinkyla")
    assert snapshot.status == "ok"
    call = fake_get.calls[0]
    assert call["url"] == "https://timma.fi/api/customers/withservicesandusers/gslug/scissor-room-matinkyla/public/v3"
    assert call["allow_redirects"] is False
    assert call["timeout"] == timma.TIMEOUT
    assert call["headers"]["User-Agent"].startswith("AgencyHunter/")


@pytest.mark.parametrize("response", [
    FakeResponse(status=302),
    FakeResponse(status=500),
    FakeResponse(body=b"<html></html>", content_type="text/html"),
    FakeResponse(body=b"{not json"),
    FakeResponse(body=b'{"status": "x"}'),
    FakeResponse(body=b"[" + b"1," * (timma.MAX_BYTES // 2) + b"1]"),
])
def test_fetch_errors(fake_get: FakeTimma, response: FakeResponse) -> None:
    fake_get.queue.append(response)
    with pytest.raises(TimmaFetchError):
        fetch_timma("natawat")
    assert response.closed


def test_fetch_404_is_not_found(fake_get: FakeTimma) -> None:
    fake_get.queue.append(FakeResponse(status=404))
    assert fetch_timma("natawat").status == "not_found"


def test_fetch_rejects_bad_slug(fake_get: FakeTimma) -> None:
    with pytest.raises(TimmaFetchError):
        fetch_timma("../admin")
    assert fake_get.calls == []


# --- Välimuisti ja Refresh ---

def test_refresh_fetches_and_caches(client_a: TestClient, make_lead: Any, fake_get: FakeTimma) -> None:
    lead = make_lead(website=RMAK_URL)
    res = client_a.post(f"/leads/{lead['id']}/timma/refresh")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["timma_fetched_at"]
    assert json.loads(body["timma_data"])["data"]["rating_count"] == 262
    assert len(fake_get.calls) == 1


def test_refresh_rejects_non_business_page(client_a: TestClient, make_lead: Any, fake_get: FakeTimma) -> None:
    lead = make_lead(website="https://timma.fi/pro/book-demo/642fff026759411f4a6cf069")
    assert client_a.post(f"/leads/{lead['id']}/timma/refresh").status_code == 422
    assert fake_get.calls == []


def test_refresh_failure_is_502_and_not_cached(client_a: TestClient, make_lead: Any, fake_get: FakeTimma) -> None:
    lead = make_lead(website=RMAK_URL)
    fake_get.queue.append(FakeResponse(status=500))
    assert client_a.post(f"/leads/{lead['id']}/timma/refresh").status_code == 502
    assert client_a.get("/leads").json()[0]["timma_data"] is None


def test_refresh_disabled(client_a: TestClient, make_lead: Any, fake_get: FakeTimma, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.main.TIMMA_IMPORT_ENABLED", False)
    lead = make_lead(website=RMAK_URL)
    assert client_a.post(f"/leads/{lead['id']}/timma/refresh").status_code == 503
    assert fake_get.calls == []


def test_refresh_other_users_lead_404(client_b: TestClient, make_lead: Any, fake_get: FakeTimma) -> None:
    lead = make_lead(website=RMAK_URL)
    assert client_b.post(f"/leads/{lead['id']}/timma/refresh").status_code == 404
    assert fake_get.calls == []


def test_ensure_timma_fetches_once(session: Session, fake_get: FakeTimma) -> None:
    from app.main import ensure_timma, lead_timma
    from app.models import Lead

    lead = Lead(user_id="u", name="R-Mak parturi", city="Espoo", website=RMAK_URL)
    session.add(lead)
    session.commit()
    first = asyncio.run(ensure_timma(session, lead))
    second = asyncio.run(ensure_timma(session, lead))
    assert first is not None and second == first
    assert len(fake_get.calls) == 1
    # Website vaihtui: vanhan sivun dataa ei käytetä
    lead.website = "https://example.fi"
    assert lead_timma(lead) is None


# --- Demo Timma-tiedoilla ---

from app.demo_site import (  # noqa: E402
    IMAGE_NOTE_EXAMPLE,
    IMAGE_NOTE_PREMIUM_EXAMPLE,
    IMAGE_NOTE_PREMIUM_TIMMA,
    IMAGE_NOTE_TIMMA,
    TIMMA_MIN_IMAGES,
    TIMMA_PRICES_NOTE,
    DemoImages,
    format_duration,
    format_price,
)
from app.utils.unsplash import DemoPhoto  # noqa: E402
from tests.conftest import FakeOpenAI  # noqa: E402
from tests.test_demo_site import VALID  # noqa: E402

BOOKING = "https://timma.fi/yritys/scissor-room-matinkyla"
EXTRA_IMAGE = "https://scaled-images.timma.fi/timma/image/upload/w_1080,c_limit,q_auto/v1/c/kolmas.jpg"


def _payload_with_images(n: int) -> bytes:
    payload = rmak_payload()
    images = payload["images"][:n]
    while len(images) < n:
        images.append({"url": EXTRA_IMAGE.replace("kolmas", f"kuva{len(images)}"), "alt": ""})
    payload["images"] = images
    return json.dumps(payload).encode()


def _unsplash_photo() -> DemoPhoto:
    return DemoPhoto(
        id="u1", raw_url="https://images.unsplash.com/photo-u1?ixid=x", photographer_name="Kuvaaja",
        photographer_url="https://unsplash.com/@k", download_location="https://api.unsplash.com/photos/u1/download",
    )


@pytest.fixture
def unsplash_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def _find(lead: Any, template: str) -> tuple[DemoImages, int]:
        calls.append(template)
        return DemoImages(hero=_unsplash_photo(), mood=[], options=[_unsplash_photo()]), 1

    monkeypatch.setattr("app.main.find_demo_images", _find)
    monkeypatch.setattr("app.main._track_downloads", lambda photos: None)
    return calls


def _demo_html(client: TestClient, lead_id: int, template: str = "barber") -> tuple[dict[str, Any], str]:
    demo = client.post(f"/leads/{lead_id}/demo", json={"template": template})
    assert demo.status_code == 200, demo.text
    page = client.get(f"/demo/{demo.json()['public_path']}")
    assert page.status_code == 200
    assert "scaled-images.timma.fi" in page.headers["content-security-policy"]
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    return demo.json(), page.text


def test_format_price_and_duration() -> None:
    assert format_price(2500) == "25 €"
    assert format_price(2550, from_price=True) == "alk. 25,50 €"
    assert [format_duration(m) for m in (15, 60, 75)] == ["15 min", "1 h", "1 h 15 min"]


@pytest.mark.parametrize("template", ["barber", "salon"])
def test_demo_with_timma_uses_prices_booking_rating_and_images(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    fake_get: FakeTimma, unsplash_calls: list[str], template: str,
) -> None:
    fake_get.queue.append(FakeResponse(body=_payload_with_images(TIMMA_MIN_IMAGES)))
    lead = make_lead(name="R-Mak parturi", phone="040 0218015", primary_type="barber_shop", website=RMAK_URL,
                     address="Pyyntitie 1 A, 02230 Espoo, Suomi", website_status="NO WEBSITE")
    fake_openai.reply = json.dumps(VALID)
    demo, html = _demo_html(client_a, lead["id"], template)

    assert len(fake_get.calls) == 1
    assert unsplash_calls == []  # kuvat yhdestä lähteestä: Timma
    stored = demo["content"]["timma"]
    assert stored["booking_url"] == BOOKING
    assert stored["rating_avg"] == 5.0 and stored["rating_count"] == 262
    assert len(stored["images"]) == TIMMA_MIN_IMAGES == 2
    # Hinnasto kategorioittain, hinnat ja kestot
    assert "Leikkaukset" in html and "Ihokarvojen poisto" in html
    assert '<span class="timma-nimi">Parturileikkaus</span><span class="timma-kesto">30 min</span><span class="timma-hinta">25 €</span>' in html
    assert TIMMA_PRICES_NOTE in html
    # Kaikki varausnapit samaan Timma-linkkiin
    booking_links = re.findall(r'<a class="nappi[^"]*" href="([^"]+)"[^>]*>Varaa aika', html)
    assert booking_links and set(booking_links) == {BOOKING}
    assert "landingPage" not in html
    # Tähdet + määrä + linkki Timmaan, ei arvostelutekstejä
    assert f'<a class="timma-arvio" href="{BOOKING}" rel="noopener noreferrer"><span aria-hidden="true">★</span> 5,0 · 262 arvostelua Timmassa</a>' in html
    # Osoite Timmasta, kuvat Timmasta, bannerin kuvarivi, ei Unsplash-mainintaa
    assert "Pyyntitie 1 A" in html
    assert "scaled-images.timma.fi" in html and "images.unsplash.com" not in html
    assert f"· {IMAGE_NOTE_TIMMA}" in html and "Unsplash" not in html
    assert '<meta name="robots" content="noindex, nofollow">' in html


def test_premium_demo_with_timma_uses_same_data_in_its_own_markup(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    fake_get: FakeTimma, unsplash_calls: list[str],
) -> None:
    fake_get.queue.append(FakeResponse(body=_payload_with_images(TIMMA_MIN_IMAGES)))
    lead = make_lead(name="R-Mak parturi", phone="040 0218015", primary_type="barber_shop", website=RMAK_URL,
                     address="Pyyntitie 1 A, 02230 Espoo, Suomi", website_status="NO WEBSITE")
    fake_openai.reply = json.dumps(VALID)
    demo, html = _demo_html(client_a, lead["id"], "premium")

    assert demo["template"] == "premium" and demo["color_scheme"] == "messinki"
    assert unsplash_calls == []  # kuvat yhdestä lähteestä: Timma
    # Timman hinnat näkyvät, joten huomautus ei puhu hinnoista (sama kuin barber-pohjassa)
    assert demo["content"]["price_note"] == "Kysykää myös muista palveluista."
    # Hinnasto kategorioittain pohjan omalla merkkauksella, rivit vievät ajanvaraukseen
    assert "<h3>Leikkaukset</h3>" in html and "<h3>Ihokarvojen poisto</h3>" in html
    assert '<span class="rivi-nimi">Parturileikkaus</span>' in html and '<span class="rivi-hinta">25 €</span>' in html
    assert f'<a class="rivi" href="{BOOKING}" rel="noopener noreferrer">' in html
    assert TIMMA_PRICES_NOTE in html
    booking_links = re.findall(r'<a class="nappi[^"]*" href="([^"]+)"[^>]*>Varaa aika', html)
    assert booking_links and set(booking_links) == {BOOKING}
    assert f'<a class="arvio" href="{BOOKING}" rel="noopener noreferrer"><span class="arvio-luku">5,0</span> 262 arvostelua Timmassa</a>' in html
    assert "Pyyntitie 1 A" in html
    assert "scaled-images.timma.fi" in html and "images.unsplash.com" not in html
    assert f"· {IMAGE_NOTE_PREMIUM_TIMMA}" in html and "Unsplash" not in html
    assert '<meta name="robots" content="noindex, nofollow">' in html


def test_premium_banner_says_hero_is_illustration_in_every_case() -> None:
    from app.demo_site import DemoImages, DemoStoredContent, image_note
    base = DemoStoredContent(**VALID, price_note="Hinnat puhelimitse.")
    assert IMAGE_NOTE_PREMIUM_EXAMPLE == "Alun kuva on kuvitusta. Muut kuvat ovat esimerkkejä"
    assert IMAGE_NOTE_PREMIUM_TIMMA == "Alun kuva on kuvitusta. Muut kuvat Timma-sivultanne"
    # Ilman muita kuvia alun kuva on silti pohjan kuvitus
    assert image_note(base, "premium") == "Alun kuva on kuvitusta"
    # Muut pohjat ennallaan
    assert image_note(base, "barber") is None and image_note(base) is None


def test_timma_with_one_image_uses_unsplash_only(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    fake_get: FakeTimma, unsplash_calls: list[str],
) -> None:
    fake_get.queue.append(FakeResponse(body=_payload_with_images(1)))
    lead = make_lead(name="R-Mak parturi", primary_type="barber_shop", website=RMAK_URL)
    fake_openai.reply = json.dumps(VALID)
    demo, html = _demo_html(client_a, lead["id"])
    assert unsplash_calls == ["barber"]
    assert demo["content"]["timma"]["images"] == []
    assert "scaled-images.timma.fi" not in html and "images.unsplash.com" in html
    assert f"· {IMAGE_NOTE_EXAMPLE}" in html and IMAGE_NOTE_TIMMA not in html
    # Hinnasto ja varauslinkki tulevat silti Timmasta
    assert "timma-hinnasto" in html and BOOKING in html


def test_demo_without_timma_is_unchanged(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    fake_get: FakeTimma, unsplash_calls: list[str],
) -> None:
    lead = make_lead(name="Parturi-kampaamo Scissors Room", primary_type="barber_shop",
                     website="https://timma.fi/pro/book-demo/642fff026759411f4a6cf069")
    fake_openai.reply = json.dumps(VALID)
    demo, html = _demo_html(client_a, lead["id"])
    assert fake_get.calls == []
    assert demo["content"]["timma"] is None
    assert "timma-hinnasto" not in html and "timma-arvio" not in html and "Varaa aika" not in html
    assert VALID["services"][0]["name"] in html
    assert f"· {IMAGE_NOTE_EXAMPLE}" in html


def test_timma_disabled_ignores_cached_data(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    fake_get: FakeTimma, unsplash_calls: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = make_lead(name="R-Mak parturi", primary_type="barber_shop", website=RMAK_URL)
    assert client_a.post(f"/leads/{lead['id']}/timma/refresh").status_code == 200
    monkeypatch.setattr("app.main.TIMMA_IMPORT_ENABLED", False)
    fake_openai.reply = json.dumps(VALID)
    demo, html = _demo_html(client_a, lead["id"])
    assert demo["content"]["timma"] is None and "timma-hinnasto" not in html
    assert len(fake_get.calls) == 1


def test_hidden_prices_not_shown(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    fake_get: FakeTimma, unsplash_calls: list[str],
) -> None:
    payload = rmak_payload()
    payload["publicSettings"]["showPrices"] = False
    fake_get.queue.append(FakeResponse(body=json.dumps(payload).encode()))
    lead = make_lead(name="R-Mak parturi", primary_type="barber_shop", website=RMAK_URL)
    fake_openai.reply = json.dumps(VALID)
    _, html = _demo_html(client_a, lead["id"])
    assert "timma-hinnasto" in html and "timma-hinta" not in html and TIMMA_PRICES_NOTE not in html


def test_text_edit_keeps_timma(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    fake_get: FakeTimma, unsplash_calls: list[str],
) -> None:
    fake_get.queue.append(FakeResponse(body=_payload_with_images(3)))
    lead = make_lead(name="R-Mak parturi", primary_type="barber_shop", website=RMAK_URL)
    fake_openai.reply = json.dumps(VALID)
    demo, _ = _demo_html(client_a, lead["id"])
    editable = {k: demo["content"][k] for k in ("hero_title", "hero_subtitle", "about_title", "about", "services", "price_note")}
    editable["hero_subtitle"] = "Uusi alaotsikko parturille Matinkylässä."
    res = client_a.patch(f"/leads/{lead['id']}/demo", json={"content": editable})
    assert res.status_code == 200, res.text
    assert res.json()["content"]["timma"] == demo["content"]["timma"]
    page = client_a.get(f"/demo/{demo['public_path']}").text
    assert "timma-hinnasto" in page and "Uusi alaotsikko" in page


# --- Autodemo ---

from tests.test_demo_publish import FakeStore, store  # noqa: E402,F401


def test_autodemo_generates_publishes_and_flags(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    fake_get: FakeTimma, unsplash_calls: list[str], store: FakeStore,
) -> None:
    fake_get.queue.append(FakeResponse(body=_payload_with_images(3)))
    lead = make_lead(name="R-Mak parturi", primary_type="barber_shop", website=RMAK_URL)
    fake_openai.reply = json.dumps(VALID)
    res = client_a.post(f"/leads/{lead['id']}/autodemo")
    assert res.status_code == 200, res.text
    demo = res.json()
    assert demo["status"] == "published" and demo["public_url"]
    assert demo["content"]["timma"]["booking_url"] == BOOKING
    body, _ = store.objects[f"demos/{demo['public_path']}.html"]
    assert b"timma-hinnasto" in body and IMAGE_NOTE_TIMMA.encode() in body
    saved = client_a.get("/leads").json()[0]
    assert saved["review_before_contact"] is True
    assert client_a.get(f"/leads/{lead['id']}/drafts").json() == []  # ei sähköpostia
    # Tarkistettu -> merkintä pois
    assert client_a.patch(f"/leads/{lead['id']}", json={"review_before_contact": False}).json()["review_before_contact"] is False


def test_autodemo_without_timma_and_without_publishing(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    fake_get: FakeTimma, unsplash_calls: list[str], store: FakeStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead = make_lead(name="Parturi-kampaamo Scissors Room", primary_type="barber_shop",
                     website="https://timma.fi/pro/book-demo/642fff026759411f4a6cf069")
    fake_openai.reply = json.dumps(VALID)
    res = client_a.post(f"/leads/{lead['id']}/autodemo")
    assert res.status_code == 200, res.text
    assert res.json()["content"]["timma"] is None and fake_get.calls == []
    monkeypatch.setattr("app.main.get_r2_config", lambda: None)
    calls_before = len(fake_openai.calls)
    assert client_a.post(f"/leads/{lead['id']}/autodemo").status_code == 503
    assert len(fake_openai.calls) == calls_before


def test_autodemo_respects_do_not_contact_and_tenant(
    client_a: TestClient, client_b: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI],
    sender_profile: dict[str, Any], store: FakeStore,
) -> None:
    lead = make_lead(name="R-Mak parturi", website=RMAK_URL)
    assert client_b.post(f"/leads/{lead['id']}/autodemo").status_code == 404
    client_a.patch(f"/leads/{lead['id']}", json={"do_not_contact": True})
    assert client_a.post(f"/leads/{lead['id']}/autodemo").status_code == 409
    assert fake_openai.calls == []
