import threading
from typing import Any

import pytest
from sqlmodel import Session, select

from app.main import (
    DETAILS_URL,
    GEOCODE_URL,
    MAX_DETAIL_CALLS,
    MAX_SEARCH_CALLS,
    GooglePlacesService,
)
from app.models import ScannedPlace

ESPOO_VIEWPORT = {
    "northeast": {"lat": 60.36, "lng": 24.95},
    "southwest": {"lat": 60.11, "lng": 24.50},
}
HUGE_VIEWPORT = {
    "northeast": {"lat": 70.0, "lng": 31.0},
    "southwest": {"lat": 60.0, "lng": 20.0},
}


class _FakeResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._data


class _FakeGoogle:
    """Mockattu requests.get: laskee kutsut ja palauttaa aina lisää sivuja."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, url: str, params: dict[str, Any], timeout: int) -> _FakeResponse:
        with self._lock:
            self.calls.append(url)
            n = len(self.calls)
        if url == GEOCODE_URL:
            return _FakeResponse({"results": [{"geometry": {"viewport": ESPOO_VIEWPORT}}]})
        if url == DETAILS_URL:
            return _FakeResponse({"result": {"name": f"Detail {params['place_id']}"}})
        # Nearby Search: aina uusi sivu -> ilman rajaa kutsuja tulisi 1 + 9 * 3 = 28
        return _FakeResponse({"results": [{"place_id": f"p{n}"}], "next_page_token": f"t{n}"})


@pytest.fixture
def fake_google(monkeypatch: pytest.MonkeyPatch) -> _FakeGoogle:
    fake = _FakeGoogle()
    monkeypatch.setattr("requests.get", fake)
    return fake


def test_grid_points_count_and_bounds() -> None:
    points, radius = GooglePlacesService.generate_grid_points(ESPOO_VIEWPORT)
    assert len(points) == 9
    assert 0 < radius <= 50_000
    for p in points:
        assert ESPOO_VIEWPORT["southwest"]["lat"] < p["lat"] < ESPOO_VIEWPORT["northeast"]["lat"]
        assert ESPOO_VIEWPORT["southwest"]["lng"] < p["lng"] < ESPOO_VIEWPORT["northeast"]["lng"]


@pytest.mark.parametrize("grid_size", [1, 2, 4])
def test_grid_points_custom_size(grid_size: int) -> None:
    points, _ = GooglePlacesService.generate_grid_points(ESPOO_VIEWPORT, grid_size=grid_size)
    assert len(points) == grid_size**2


def test_grid_radius_capped_at_50km() -> None:
    _, radius = GooglePlacesService.generate_grid_points(HUGE_VIEWPORT)
    assert radius == 50_000


def test_search_calls_capped(fake_google: _FakeGoogle) -> None:
    service = GooglePlacesService("AIza-test")
    places = service.search_grid("Espoo", "parturi")

    assert len(fake_google.calls) == MAX_SEARCH_CALLS
    assert service._search_call_count == MAX_SEARCH_CALLS
    assert len(places) == MAX_SEARCH_CALLS - 1  # 1 geocode + loput nearby-sivuja


def test_make_request_search_limit(fake_google: _FakeGoogle) -> None:
    service = GooglePlacesService("AIza-test")
    for _ in range(MAX_SEARCH_CALLS + 10):
        service._make_request(GEOCODE_URL, {}, call_type="search")
    assert len(fake_google.calls) == MAX_SEARCH_CALLS
    assert service._make_request(GEOCODE_URL, {}, call_type="search") == {}


def test_make_request_detail_limit(fake_google: _FakeGoogle) -> None:
    service = GooglePlacesService("AIza-test")
    for i in range(MAX_DETAIL_CALLS + 10):
        service._make_request(DETAILS_URL, {"place_id": f"x{i}"}, call_type="detail")
    assert len(fake_google.calls) == MAX_DETAIL_CALLS


def test_enrich_with_details_capped(fake_google: _FakeGoogle, session: Session) -> None:
    service = GooglePlacesService("AIza-test")
    unique_places = {f"pid-{i}": {"place_id": f"pid-{i}"} for i in range(MAX_DETAIL_CALLS + 20)}

    enriched = service.enrich_with_details(unique_places, session)

    assert len(fake_google.calls) == MAX_DETAIL_CALLS
    assert len(enriched) == MAX_DETAIL_CALLS
    assert len(session.exec(select(ScannedPlace)).all()) == MAX_DETAIL_CALLS


def test_enrich_skips_already_scanned(fake_google: _FakeGoogle, session: Session) -> None:
    session.add(ScannedPlace(google_place_id="pid-0"))
    session.commit()

    service = GooglePlacesService("AIza-test")
    enriched = service.enrich_with_details({"pid-0": {}, "pid-1": {"place_id": "pid-1"}}, session)

    assert len(fake_google.calls) == 1
    assert [e["place_id"] for e in enriched] == ["pid-1"]
