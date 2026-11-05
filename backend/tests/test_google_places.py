import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from app.main import (
    GEOCODE_URL,
    MAX_PAGES_PER_CELL,
    MAX_SEARCH_CALLS,
    PLACES_FIELD_MASK,
    PLACES_TEXT_SEARCH_URL,
    GooglePlacesService,
    normalize_place,
)

KAUNIAINEN_VIEWPORT = {
    "northeast": {"lat": 60.2260, "lng": 24.7480},
    "southwest": {"lat": 60.2000, "lng": 24.6990},
}

EXPECTED_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
    "places.websiteUri,places.rating,places.userRatingCount,places.businessStatus,"
    "places.primaryType,places.googleMapsUri,nextPageToken"
)


class _FakeResponse:
    def __init__(self, data: dict[str, Any], status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code
        self.text = str(data)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._data


def _place(pid: str, status: str = "OPERATIONAL", **extra: Any) -> dict[str, Any]:
    return {"id": pid, "displayName": {"text": f"Yritys {pid}"}, "businessStatus": status, **extra}


class _FakeGoogle:
    """Mockattu requests.get (Geocoding) + requests.post (Text Search). Kirjaa kaikki kutsut."""

    def __init__(self, pages_per_cell: int | None = None) -> None:
        # pages_per_cell=None -> jokaisessa vastauksessa aina nextPageToken (loputon sivutus)
        self.pages_per_cell = pages_per_cell
        self.gets: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.places_by_call: list[list[dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any], timeout: int) -> _FakeResponse:
        with self._lock:
            self.gets.append({"url": url, "params": params})
        return _FakeResponse({"results": [{"geometry": {"viewport": KAUNIAINEN_VIEWPORT}}]})

    def post(self, url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> _FakeResponse:
        with self._lock:
            self.posts.append({"url": url, "json": json, "headers": headers})
            n = len(self.posts)
        page = int(json.get("pageToken", "page-1").split("-")[1])
        if self.places_by_call:
            places = self.places_by_call.pop(0)
        else:
            places = [_place(f"p{n}")]
        data: dict[str, Any] = {"places": places}
        if self.pages_per_cell is None or page < self.pages_per_cell:
            data["nextPageToken"] = f"page-{page + 1}"
        return _FakeResponse(data)


@pytest.fixture
def fake_google(monkeypatch: pytest.MonkeyPatch) -> _FakeGoogle:
    fake = _FakeGoogle()
    monkeypatch.setattr("requests.get", fake.get)
    monkeypatch.setattr("requests.post", fake.post)
    return fake


# --- Grid ---

def test_grid_cells_cover_viewport_without_gaps() -> None:
    cells = GooglePlacesService.generate_grid_cells(KAUNIAINEN_VIEWPORT)
    assert len(cells) == 9

    sw, ne = KAUNIAINEN_VIEWPORT["southwest"], KAUNIAINEN_VIEWPORT["northeast"]
    assert min(c["low"]["latitude"] for c in cells) == pytest.approx(sw["lat"])
    assert min(c["low"]["longitude"] for c in cells) == pytest.approx(sw["lng"])
    assert max(c["high"]["latitude"] for c in cells) == pytest.approx(ne["lat"])
    assert max(c["high"]["longitude"] for c in cells) == pytest.approx(ne["lng"])

    for c in cells:
        assert c["low"]["latitude"] < c["high"]["latitude"]
        assert c["low"]["longitude"] < c["high"]["longitude"]

    # Vierekkäiset ruudut jakavat reunan (ei aukkoja eikä limitystä)
    assert cells[0]["high"]["longitude"] == pytest.approx(cells[1]["low"]["longitude"])
    assert cells[0]["high"]["latitude"] == pytest.approx(cells[3]["low"]["latitude"])


@pytest.mark.parametrize("grid_size", [1, 2, 4])
def test_grid_cells_custom_size(grid_size: int) -> None:
    assert len(GooglePlacesService.generate_grid_cells(KAUNIAINEN_VIEWPORT, grid_size)) == grid_size**2


# --- Text Search -pyynnön muoto ---

def test_text_search_sends_field_mask_and_key_headers(fake_google: _FakeGoogle) -> None:
    fake_google.pages_per_cell = 1
    service = GooglePlacesService("AIza-test")
    rect = service.generate_grid_cells(KAUNIAINEN_VIEWPORT)[0]

    service.search_cell(rect, "parturi")

    assert len(fake_google.posts) == 1
    call = fake_google.posts[0]
    assert call["url"] == PLACES_TEXT_SEARCH_URL == "https://places.googleapis.com/v1/places:searchText"
    assert call["headers"]["X-Goog-FieldMask"] == EXPECTED_FIELD_MASK == PLACES_FIELD_MASK
    assert " " not in call["headers"]["X-Goog-FieldMask"]
    assert call["headers"]["X-Goog-Api-Key"] == "AIza-test"
    assert call["json"]["textQuery"] == "parturi"
    assert call["json"]["locationRestriction"] == {"rectangle": rect}
    assert "key" not in call["json"]


def test_geocode_uses_geocoding_api(fake_google: _FakeGoogle) -> None:
    service = GooglePlacesService("AIza-test")
    assert service.get_city_bounds("Kauniainen") == KAUNIAINEN_VIEWPORT
    assert fake_google.gets[0]["url"] == GEOCODE_URL
    assert fake_google.gets[0]["params"]["address"] == "Kauniainen, Finland"


# --- Paginointi ---

def test_pagination_stops_at_max_pages(fake_google: _FakeGoogle) -> None:
    service = GooglePlacesService("AIza-test")
    places = service.search_cell(service.generate_grid_cells(KAUNIAINEN_VIEWPORT)[0], "parturi")

    assert len(fake_google.posts) == MAX_PAGES_PER_CELL == 3
    assert len(places) == 3


def test_pagination_stops_without_next_token(fake_google: _FakeGoogle) -> None:
    fake_google.pages_per_cell = 2
    service = GooglePlacesService("AIza-test")
    service.search_cell(service.generate_grid_cells(KAUNIAINEN_VIEWPORT)[0], "parturi")
    assert len(fake_google.posts) == 2


def test_page_token_request_keeps_other_params_identical(fake_google: _FakeGoogle) -> None:
    service = GooglePlacesService("AIza-test")
    service.search_cell(service.generate_grid_cells(KAUNIAINEN_VIEWPORT)[0], "parturi")

    first, second = fake_google.posts[0]["json"], fake_google.posts[1]["json"]
    assert "pageToken" not in first
    assert second["pageToken"] == "page-2"
    assert {k: v for k, v in second.items() if k != "pageToken"} == first


# --- Tulokset ---

def test_normalize_place_maps_fields() -> None:
    raw = {
        "id": "ChIJ1",
        "displayName": {"text": "Parturi X", "languageCode": "fi"},
        "formattedAddress": "Katu 1, 02700 Kauniainen",
        "nationalPhoneNumber": "09 123 456",
        "websiteUri": "https://x.fi/",
        "rating": 4.6,
        "userRatingCount": 87,
        "businessStatus": "OPERATIONAL",
        "primaryType": "hair_salon",
        "googleMapsUri": "https://maps.google.com/?cid=1",
    }
    assert normalize_place(raw) == {
        "place_id": "ChIJ1",
        "name": "Parturi X",
        "address": "Katu 1, 02700 Kauniainen",
        "phone": "09 123 456",
        "website": "https://x.fi/",
        "rating": 4.6,
        "review_count": 87,
        "business_status": "OPERATIONAL",
        "primary_type": "hair_salon",
        "maps_url": "https://maps.google.com/?cid=1",
    }


def test_normalize_place_handles_missing_fields() -> None:
    result = normalize_place({"id": "ChIJ2"})
    assert result["place_id"] == "ChIJ2"
    assert result["name"] == ""
    assert result["rating"] is None
    assert result["review_count"] is None


def test_search_grid_dedupes_and_drops_permanently_closed(fake_google: _FakeGoogle) -> None:
    fake_google.pages_per_cell = 1
    fake_google.places_by_call = [
        [_place("a"), _place("closed", status="CLOSED_PERMANENTLY")],
        [_place("a"), _place("temp", status="CLOSED_TEMPORARILY")],
    ]
    service = GooglePlacesService("AIza-test")
    results = service.search_grid("Kauniainen", "parturi")

    ids = {r["place_id"] for r in results}
    assert "closed" not in ids
    assert {"a", "temp"} <= ids
    assert [r["place_id"] for r in results].count("a") == 1
    assert next(r for r in results if r["place_id"] == "temp")["business_status"] == "CLOSED_TEMPORARILY"


def test_places_api_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "requests.post",
        lambda *a, **k: _FakeResponse({"error": {"status": "PERMISSION_DENIED"}}, status_code=403),
    )
    service = GooglePlacesService("AIza-test")
    assert service.search_cell(service.generate_grid_cells(KAUNIAINEN_VIEWPORT)[0], "parturi") == []


# --- Turvakytkin ---

def test_search_calls_capped(fake_google: _FakeGoogle) -> None:
    # Ilman rajaa: 1 geocode + 9 ruutua * 3 sivua = 28 kutsua
    service = GooglePlacesService("AIza-test")
    results = service.search_grid("Kauniainen", "parturi")

    assert len(fake_google.gets) + len(fake_google.posts) == MAX_SEARCH_CALLS
    assert service.calls_used == MAX_SEARCH_CALLS
    assert len(results) == MAX_SEARCH_CALLS - 1


def test_search_cap_holds_under_concurrency(fake_google: _FakeGoogle) -> None:
    service = GooglePlacesService("AIza-test")
    rect = service.generate_grid_cells(KAUNIAINEN_VIEWPORT)[0]
    barrier = threading.Barrier(20)

    def _call(_i: int) -> None:
        barrier.wait()
        for _ in range(5):
            service._post_json(PLACES_TEXT_SEARCH_URL, {"textQuery": "x", "locationRestriction": {"rectangle": rect}})

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(_call, range(20)))

    assert len(fake_google.posts) == MAX_SEARCH_CALLS
    assert service.calls_used == MAX_SEARCH_CALLS
