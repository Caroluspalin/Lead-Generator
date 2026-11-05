import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

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
ROOT = GooglePlacesService.viewport_to_rectangle(KAUNIAINEN_VIEWPORT)

EXPECTED_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
    "places.websiteUri,places.rating,places.userRatingCount,places.businessStatus,"
    "places.primaryType,places.googleMapsUri,nextPageToken"
)

# Montako tulosta alue palauttaa yhteensä (kaikki sivut); rect -> määrä
AreaCount = Callable[[dict[str, Any]], int]


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


def _area_key(rect: dict[str, Any]) -> str:
    lo, hi = rect["low"], rect["high"]
    return f"{lo['latitude']:.5f},{lo['longitude']:.5f},{hi['latitude']:.5f},{hi['longitude']:.5f}"


class _FakeGoogle:
    """Mockattu requests.get (Geocoding) + requests.post (Text Search). Kirjaa kaikki kutsut.

    area_count(rect) kertoo montako yritystä alueella on; vastaus sivutetaan 20 kpl/sivu
    ja katkaistaan 60:een kuten oikea API.
    """

    def __init__(self, area_count: AreaCount) -> None:
        self.area_count = area_count
        self.gets: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []
        self.override_places: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, url: str, params: dict[str, Any], timeout: int) -> _FakeResponse:
        with self._lock:
            self.gets.append({"url": url, "params": params})
        return _FakeResponse({"results": [{"geometry": {"viewport": KAUNIAINEN_VIEWPORT}}]})

    def post(self, url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> _FakeResponse:
        with self._lock:
            self.posts.append({"url": url, "json": json, "headers": headers})
        rect = json["locationRestriction"]["rectangle"]
        key = _area_key(rect)
        page = int(json.get("pageToken", "page-1").split("-")[1])

        if key in self.override_places:
            return _FakeResponse({"places": self.override_places[key]})

        total = min(60, self.area_count(rect))
        start = (page - 1) * 20
        places = [_place(f"{key}#{i}") for i in range(start, min(start + 20, total))]
        data: dict[str, Any] = {"places": places}
        if start + 20 < total:
            data["nextPageToken"] = f"page-{page + 1}"
        return _FakeResponse(data)

    def text_search_areas(self) -> list[str]:
        return [_area_key(p["json"]["locationRestriction"]["rectangle"]) for p in self.posts if "pageToken" not in p["json"]]


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> Callable[[AreaCount], _FakeGoogle]:
    def _install(area_count: AreaCount) -> _FakeGoogle:
        fake = _FakeGoogle(area_count)
        monkeypatch.setattr("requests.get", fake.get)
        monkeypatch.setattr("requests.post", fake.post)
        return fake

    return _install


def _always(n: int) -> AreaCount:
    return lambda _rect: n


# --- Suorakaiteet ---

def test_viewport_to_rectangle() -> None:
    assert ROOT == {
        "low": {"latitude": 60.2000, "longitude": 24.6990},
        "high": {"latitude": 60.2260, "longitude": 24.7480},
    }


def test_split_rectangle_covers_area_without_gaps() -> None:
    quads = GooglePlacesService.split_rectangle(ROOT)
    assert len(quads) == 4
    assert min(q["low"]["latitude"] for q in quads) == pytest.approx(ROOT["low"]["latitude"])
    assert min(q["low"]["longitude"] for q in quads) == pytest.approx(ROOT["low"]["longitude"])
    assert max(q["high"]["latitude"] for q in quads) == pytest.approx(ROOT["high"]["latitude"])
    assert max(q["high"]["longitude"] for q in quads) == pytest.approx(ROOT["high"]["longitude"])
    for q in quads:
        assert q["low"]["latitude"] < q["high"]["latitude"]
        assert q["low"]["longitude"] < q["high"]["longitude"]
    # Vierekkäiset jakavat reunan
    assert quads[0]["high"]["longitude"] == pytest.approx(quads[1]["low"]["longitude"])
    assert quads[0]["high"]["latitude"] == pytest.approx(quads[2]["low"]["latitude"])
    area = lambda r: (r["high"]["latitude"] - r["low"]["latitude"]) * (r["high"]["longitude"] - r["low"]["longitude"])  # noqa: E731
    assert sum(area(q) for q in quads) == pytest.approx(area(ROOT))


# --- Text Search -pyynnön muoto ---

def test_text_search_sends_field_mask_and_key_headers(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(5))
    service = GooglePlacesService("AIza-test")
    service.search_cell(ROOT, "parturi")

    assert len(fake.posts) == 1
    call = fake.posts[0]
    assert call["url"] == PLACES_TEXT_SEARCH_URL == "https://places.googleapis.com/v1/places:searchText"
    assert call["headers"]["X-Goog-FieldMask"] == EXPECTED_FIELD_MASK == PLACES_FIELD_MASK
    assert " " not in call["headers"]["X-Goog-FieldMask"]
    assert call["headers"]["X-Goog-Api-Key"] == "AIza-test"
    assert call["json"]["textQuery"] == "parturi"
    assert call["json"]["locationRestriction"] == {"rectangle": ROOT}
    assert call["json"]["pageSize"] == 20
    assert "key" not in call["json"]


def test_geocode_uses_geocoding_api(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(0))
    service = GooglePlacesService("AIza-test")
    assert service.get_city_bounds("Kauniainen") == KAUNIAINEN_VIEWPORT
    assert fake.gets[0]["url"] == GEOCODE_URL
    assert fake.gets[0]["params"]["address"] == "Kauniainen, Finland"


# --- Paginointi ---

def test_pagination_stops_at_max_pages(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(500))
    places = GooglePlacesService("AIza-test").search_cell(ROOT, "parturi")
    assert len(fake.posts) == MAX_PAGES_PER_CELL == 3
    assert len(places) == 60


def test_pagination_stops_without_next_token(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(35))
    places = GooglePlacesService("AIza-test").search_cell(ROOT, "parturi")
    assert len(fake.posts) == 2
    assert len(places) == 35


def test_page_token_request_keeps_other_params_identical(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(60))
    GooglePlacesService("AIza-test").search_cell(ROOT, "parturi")
    first, second = fake.posts[0]["json"], fake.posts[1]["json"]
    assert "pageToken" not in first
    assert second["pageToken"] == "page-2"
    assert {k: v for k, v in second.items() if k != "pageToken"} == first


# --- Mukautuva ruudukko ---

def test_small_city_uses_one_text_search(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(20))
    service = GooglePlacesService("AIza-test")
    results = service.search_grid("Kauniainen", "parturi")

    assert len(results) == 20
    assert len(fake.gets) == 1
    assert len(fake.posts) == 1
    assert service.calls_used == 2
    assert fake.text_search_areas() == [_area_key(ROOT)]


def test_small_city_with_two_pages_does_not_split(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(45))
    service = GooglePlacesService("AIza-test")
    assert len(service.search_grid("Kauniainen", "parturi")) == 45
    assert len(fake.posts) == 3  # 3 sivua mutta ei täynnä (45 < 60)
    assert fake.text_search_areas() == [_area_key(ROOT)]


def test_big_city_splits_saturated_area_into_quadrants(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    root_key = _area_key(ROOT)
    fake = google(lambda rect: 200 if _area_key(rect) == root_key else 25)
    service = GooglePlacesService("AIza-test")
    service.search_grid("Kauniainen", "parturi")

    areas = fake.text_search_areas()
    assert areas[0] == root_key
    assert sorted(areas[1:]) == sorted(_area_key(q) for q in GooglePlacesService.split_rectangle(ROOT))
    # 1 geocode + 3 sivua koko alueelle + 4 neljännestä * 2 sivua
    assert service.calls_used == 1 + 3 + 4 * 2


def test_only_saturated_quadrants_split_further(
    google: Callable[[AreaCount], _FakeGoogle], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.MAX_SEARCH_CALLS", 1000)
    quads = GooglePlacesService.split_rectangle(ROOT)
    dense = {_area_key(ROOT), _area_key(quads[3])}
    fake = google(lambda rect: 200 if _area_key(rect) in dense else 10)
    GooglePlacesService("AIza-test").search_grid("Kauniainen", "parturi")

    areas = fake.text_search_areas()
    assert len(areas) == 1 + 4 + 4
    assert sorted(areas[5:]) == sorted(_area_key(q) for q in GooglePlacesService.split_rectangle(quads[3]))


def test_split_depth_is_limited(
    google: Callable[[AreaCount], _FakeGoogle], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.MAX_SEARCH_CALLS", 1000)
    fake = google(_always(1000))
    GooglePlacesService("AIza-test").search_grid("Helsinki", "parturi")
    assert len(fake.text_search_areas()) == 1 + 4 + 16  # MAX_SPLIT_DEPTH = 2


def test_dense_city_stops_at_max_search_calls(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(1000))
    service = GooglePlacesService("AIza-test")
    results = service.search_grid("Helsinki", "parturi")

    assert len(fake.gets) + len(fake.posts) == MAX_SEARCH_CALLS == 15
    assert service.calls_used == MAX_SEARCH_CALLS
    assert len(results) > 60


def test_usage_reports_calls_and_cost(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    google(_always(20))
    service = GooglePlacesService("AIza-test")
    service.search_grid("Kauniainen", "parturi")

    usage = service.usage()
    assert usage.api_calls == 2
    assert usage.geocode_calls == 1
    assert usage.text_search_calls == 1
    assert usage.estimated_cost_usd == pytest.approx(0.005 + 0.035)


def test_usage_cost_for_previous_kauniainen_grid() -> None:
    # Edellinen 3x3-grid: 1 geocode + 9 text search -> ~$0.32
    service = GooglePlacesService("AIza-test")
    service._calls = {"geocode": 1, "text_search": 9}
    assert service.usage().estimated_cost_usd == pytest.approx(0.32)


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


def test_search_grid_dedupes_and_drops_permanently_closed(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(0))
    fake.override_places[_area_key(ROOT)] = [
        _place("a"),
        _place("a"),
        _place("closed", status="CLOSED_PERMANENTLY"),
        _place("temp", status="CLOSED_TEMPORARILY"),
    ]
    results = GooglePlacesService("AIza-test").search_grid("Kauniainen", "parturi")

    ids = [r["place_id"] for r in results]
    assert sorted(ids) == ["a", "temp"]
    assert next(r for r in results if r["place_id"] == "temp")["business_status"] == "CLOSED_TEMPORARILY"


def test_places_api_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "requests.post",
        lambda *a, **k: _FakeResponse({"error": {"status": "PERMISSION_DENIED"}}, status_code=403),
    )
    assert GooglePlacesService("AIza-test").search_cell(ROOT, "parturi") == []


# --- Turvakytkin rinnakkain ---

def test_search_cap_holds_under_concurrency(google: Callable[[AreaCount], _FakeGoogle]) -> None:
    fake = google(_always(5))
    service = GooglePlacesService("AIza-test")
    barrier = threading.Barrier(20)

    def _call(_i: int) -> None:
        barrier.wait()
        for _ in range(5):
            service._post_json(PLACES_TEXT_SEARCH_URL, {"textQuery": "x", "locationRestriction": {"rectangle": ROOT}})

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(_call, range(20)))

    assert len(fake.posts) == MAX_SEARCH_CALLS
    assert service.calls_used == MAX_SEARCH_CALLS
