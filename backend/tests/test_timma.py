import json
import asyncio
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
