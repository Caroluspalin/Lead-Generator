"""Uudet liidit -haku: määrä, kutsuraja, suodattimet ja paikkojen tilat (seen / in_pipeline / dismissed)."""
import hashlib
from pathlib import Path
from typing import Any, Callable

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session, select

from app.main import (
    MAX_SEARCH_CALLS,
    GoogleSearchResult,
    GooglePlacesService,
    SearchFilters,
    city_from_address,
    collect_new_leads,
    could_match,
)
from app.models import Demo, Lead, PlaceStatus

VIEWPORT = {"northeast": {"lat": 60.2260, "lng": 24.7480}, "southwest": {"lat": 60.2000, "lng": 24.6990}}
CITY_RECT = GooglePlacesService.viewport_to_rectangle(VIEWPORT)


def _key(rect: dict[str, Any]) -> str:
    lo, hi = rect["low"], rect["high"]
    raw = f"{lo['latitude']:.5f},{lo['longitude']:.5f},{hi['latitude']:.5f},{hi['longitude']:.5f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


class _Resp:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self.status_code = 200
        self.text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._data


class FakePlaces:
    """Geocoding + Text Search. area_count(rect) = yritysten määrä alueella (max 60, 20/sivu).

    Paikat ilman verkkosivua -> analyze_website(None) ei tee verkkopyyntöä.
    """

    def __init__(self, area_count: Callable[[dict[str, Any]], int]) -> None:
        self.area_count = area_count
        self.calls = 0
        self.areas: list[str] = []

    def get(self, url: str, params: dict[str, Any], timeout: int) -> _Resp:
        self.calls += 1
        return _Resp({"results": [{"geometry": {"viewport": VIEWPORT}}]})

    def post(self, url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> _Resp:
        self.calls += 1
        rect = json["locationRestriction"]["rectangle"]
        key = _key(rect)
        page = int(json.get("pageToken", "p-1").split("-")[1])
        if page == 1:
            self.areas.append(key)
        total = min(60, self.area_count(rect))
        start = (page - 1) * 20
        places = [
            {"id": f"P{key}_{i}", "displayName": {"text": f"Yritys {key} {i}"}, "businessStatus": "OPERATIONAL",
             "formattedAddress": f"Katu {i}, 02700 Kauniainen, Suomi", "rating": 4.5, "userRatingCount": 40}
            for i in range(start, min(start + 20, total))
        ]
        data: dict[str, Any] = {"places": places}
        if start + 20 < total:
            data["nextPageToken"] = f"p-{page + 1}"
        return _Resp(data)


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[dict[str, Any]], int]], FakePlaces]:
    def _install(area_count: Callable[[dict[str, Any]], int]) -> FakePlaces:
        fake = FakePlaces(area_count)
        monkeypatch.setattr("app.main.USE_LIVE_GOOGLE", True)
        monkeypatch.setattr("app.main.GOOGLE_API_KEY", "AIza-test")
        monkeypatch.setattr("requests.get", fake.get)
        monkeypatch.setattr("requests.post", fake.post)
        return fake

    return _install


def _search(client: TestClient, **params: Any) -> dict[str, Any]:
    res = client.get("/search", params={"business_type": "parturi", "city": "Kauniainen", **params})
    assert res.status_code == 200, res.text
    return res.json()


# --- Määrä ja kutsuraja ---

def test_stops_when_requested_count_is_reached(client_a: TestClient, live: Any) -> None:
    fake = live(lambda _r: 1000)
    body = _search(client_a, count=5)
    assert len(body["results"]) == 5
    assert body["summary"]["found"] == 5
    assert body["summary"]["stop_reason"] == "target_reached"
    # Geocode + yksi Text Search -sivu riitti: seuraavia sivuja ei haettu
    assert fake.calls == 2
    assert body["usage"]["api_calls"] == 2


def test_continues_paging_until_count_of_new_leads(client_a: TestClient, live: Any) -> None:
    fake = live(lambda _r: 1000)
    _search(client_a, count=20)
    # Samat 20 on nyt nähty -> toinen haku jatkaa seuraaville sivuille
    body = _search(client_a, count=20)
    assert body["summary"]["found"] == 20
    assert body["summary"]["skipped_seen"] == 20
    assert fake.calls == 2 + 3


def test_call_limit_holds_with_many_saturated_areas(client_a: TestClient, live: Any) -> None:
    fake = live(lambda _r: 1000)
    # Mikään ei täytä suodatinta -> määrä ei täyty koskaan, vain raja pysäyttää
    body = _search(client_a, count=100, expand_neighbors="true", min_score=100)
    assert fake.calls == MAX_SEARCH_CALLS
    assert body["usage"]["api_calls"] == MAX_SEARCH_CALLS
    assert body["summary"]["stop_reason"] == "call_limit"
    assert body["summary"]["found"] == 0
    assert body["summary"]["filtered_out"] > 0


def test_call_limit_holds_when_expanding_to_neighbors(client_a: TestClient, live: Any) -> None:
    fake = live(lambda _r: 40)  # 2 sivua per alue, ei jakoa
    body = _search(client_a, count=100, expand_neighbors="true", min_score=100)
    assert fake.calls <= MAX_SEARCH_CALLS
    assert body["summary"]["searched_neighbors"] is True
    assert body["summary"]["stop_reason"] == "call_limit"
    assert len(fake.areas) > 1
    assert fake.areas[1:] == [_key(r) for r in GooglePlacesService.neighbor_rectangles(CITY_RECT)][: len(fake.areas) - 1]


def test_without_neighbors_small_city_is_exhausted(client_a: TestClient, live: Any) -> None:
    fake = live(lambda _r: 10)
    body = _search(client_a, count=20)
    assert body["summary"] == {
        **body["summary"], "found": 10, "stop_reason": "area_exhausted", "searched_neighbors": False,
    }
    assert fake.calls == 2


def test_neighbors_fill_the_count_when_city_runs_out(client_a: TestClient, live: Any) -> None:
    fake = live(lambda _r: 10)
    body = _search(client_a, count=25, expand_neighbors="true")
    assert body["summary"]["found"] == 25
    assert body["summary"]["searched_neighbors"] is True
    assert fake.calls == 1 + 3


def test_neighbor_rectangles_surround_without_overlap() -> None:
    rects = GooglePlacesService.neighbor_rectangles(CITY_RECT)
    assert len(rects) == 8
    assert CITY_RECT not in rects
    lats = sorted({round(r["low"]["latitude"], 6) for r in rects})
    assert len(lats) == 3


def test_result_city_comes_from_address() -> None:
    assert city_from_address("Kauppakatu 1, 40100 Jyväskylä, Suomi") == "Jyväskylä"
    assert city_from_address("Esimerkkikatu 1, Espoo") is None


# --- Tilat: dismissed, in_pipeline, seen ---

def test_dismissed_and_pipeline_never_return(client_a: TestClient, make_lead: Any) -> None:
    first = _search(client_a)["results"]
    dismissed, saved = first[0], first[1]
    assert client_a.post(f"/places/{dismissed['place_id']}/dismiss").json()["status"] == "dismissed"
    make_lead(name=saved["name"], google_place_id=saved["place_id"])

    for only_new in ("true", "false"):
        ids = {r["place_id"] for r in _search(client_a, only_new=only_new)["results"]}
        assert dismissed["place_id"] not in ids
        assert saved["place_id"] not in ids


def test_seen_filtered_only_with_only_new(client_a: TestClient) -> None:
    first = _search(client_a)
    assert len(first["results"]) == 9
    again = _search(client_a)
    assert again["results"] == []
    assert again["summary"]["skipped_seen"] == 9
    assert len(_search(client_a, only_new="false")["results"]) == 9


def test_seen_does_not_downgrade_pipeline_or_dismissed(client_a: TestClient, make_lead: Any, session: Session) -> None:
    first = _search(client_a, only_new="false")["results"]
    make_lead(name=first[0]["name"], google_place_id=first[0]["place_id"])
    client_a.post(f"/places/{first[1]['place_id']}/dismiss")
    _search(client_a, only_new="false")
    rows = {r.place_id: r.status for r in session.exec(select(PlaceStatus)).all()}
    assert rows[first[0]["place_id"]] == "in_pipeline"
    assert rows[first[1]["place_id"]] == "dismissed"


def test_only_returned_results_are_marked_seen(client_a: TestClient, session: Session) -> None:
    returned = {r["place_id"] for r in _search(client_a, count=3)["results"]}
    seen = {r.place_id for r in session.exec(select(PlaceStatus)).all()}
    assert seen == returned
    # Loput tulevat seuraavassa haussa
    assert len(_search(client_a)["results"]) == 6


def test_deleting_lead_makes_it_seen_not_dismissed(client_a: TestClient, make_lead: Any, session: Session) -> None:
    first = _search(client_a)["results"]
    lead = make_lead(name=first[0]["name"], google_place_id=first[0]["place_id"])
    client_a.delete(f"/leads/{lead['id']}")
    status = session.exec(select(PlaceStatus).where(PlaceStatus.place_id == first[0]["place_id"])).one()
    assert status.status == "seen"
    assert first[0]["place_id"] in {r["place_id"] for r in _search(client_a, only_new="false")["results"]}


def test_dismiss_from_pipeline_removes_lead_and_demo(client_a: TestClient, make_lead: Any, session: Session) -> None:
    lead = make_lead(google_place_id="ChIJpipeline1")
    session.add(Demo(user_id="user-a", lead_id=lead["id"], template="services", color_scheme="x",
                     content_json="{}", html="<p>", public_token="tok-pipeline-1"))
    session.commit()

    body = client_a.post("/places/ChIJpipeline1/dismiss").json()
    assert body["removed_lead_id"] == lead["id"]
    assert client_a.get("/leads").json() == []
    session.expire_all()
    assert session.exec(select(Demo)).all() == []
    assert [d["place_id"] for d in client_a.get("/places/dismissed").json()] == ["ChIJpipeline1"]


def test_restore_dismissed_place(client_a: TestClient) -> None:
    first = _search(client_a)["results"]
    pid = first[0]["place_id"]
    client_a.post(f"/places/{pid}/dismiss")
    listed = client_a.get("/places/dismissed").json()
    assert listed[0]["place_id"] == pid
    assert listed[0]["maps_url"] == f"https://www.google.com/maps/place/?q=place_id:{pid}"

    assert client_a.delete(f"/places/{pid}/dismiss").json() == {"ok": True}
    assert client_a.get("/places/dismissed").json() == []
    # Palautettu on taas uusi
    assert pid in {r["place_id"] for r in _search(client_a)["results"]}
    assert client_a.delete(f"/places/{pid}/dismiss").status_code == 404


def test_manual_lead_ids_cannot_be_dismissed(client_a: TestClient) -> None:
    assert client_a.post("/places/manual-123/dismiss").status_code == 422


# --- Tenant-isolaatio ---

def test_tenant_isolation_of_place_statuses(client_a: TestClient, client_b: TestClient) -> None:
    a_first = _search(client_a)["results"]
    pid = a_first[0]["place_id"]
    client_a.post(f"/places/{pid}/dismiss")

    # A:n nähdyt ja hylätyt eivät vaikuta B:hen
    b_results = _search(client_b)["results"]
    assert len(b_results) == 9
    assert pid in {r["place_id"] for r in b_results}
    assert client_b.get("/places/dismissed").json() == []
    # B ei voi palauttaa A:n hylkäämää
    assert client_b.delete(f"/places/{pid}/dismiss").status_code == 404
    assert [d["place_id"] for d in client_a.get("/places/dismissed").json()] == [pid]


def test_b_dismissing_does_not_remove_a_lead(client_a: TestClient, client_b: TestClient, make_lead: Any) -> None:
    make_lead(google_place_id="ChIJshared1")
    client_b.post("/places/ChIJshared1/dismiss")
    assert len(client_a.get("/leads").json()) == 1
    assert client_a.get("/places/dismissed").json() == []


# --- Suodattimet ---

def test_status_and_score_filters(client_a: TestClient) -> None:
    body = _search(client_a, status=["no_website"], only_new="false")
    assert {r["website_status"] for r in body["results"]} == {"NO WEBSITE"}
    assert body["summary"]["filtered_out"] > 0

    multi = _search(client_a, status=["broken", "insecure"], only_new="false")["results"]
    assert {r["website_status"] for r in multi} == {"BROKEN WEBSITE", "INSECURE"}

    high = _search(client_a, min_score=70, only_new="false")["results"]
    assert high and all(r["lead_score"] >= 70 for r in high)

    open_only = _search(client_a, exclude_closed="true", only_new="false")["results"]
    assert all(r["business_status"] != "CLOSED_TEMPORARILY" for r in open_only)


def test_unknown_status_filter_is_rejected(client_a: TestClient) -> None:
    res = client_a.get("/search", params={"business_type": "parturi", "city": "Espoo", "status": "kaikki"})
    assert res.status_code == 422


def _place(**extra: Any) -> dict[str, Any]:
    return {"place_id": "x", "name": "N", "address": "A", "website": None, "rating": 4.5, "review_count": 40,
            "business_status": "OPERATIONAL", **extra}


def test_could_match_skips_sites_that_cannot_pass() -> None:
    no_site = SearchFilters(statuses=["no_website"])
    assert could_match(_place(), no_site)
    assert not could_match(_place(website="https://a.fi"), no_site)
    assert not could_match(_place(website="https://facebook.com/a"), no_site)
    assert could_match(_place(website="https://facebook.com/a"), SearchFilters(statuses=["social_only"]))
    # Hyvä sivu ei voi koskaan nousta 90 pisteeseen
    assert not could_match(_place(website="https://a.fi"), SearchFilters(min_score=85))
    assert could_match(_place(), SearchFilters(min_score=85))
    assert not could_match(_place(business_status="CLOSED_TEMPORARILY"), SearchFilters(exclude_closed=True))


def test_not_mobile_filter_matches_insecure_without_viewport() -> None:
    analyzed: list[list[dict[str, Any]]] = []

    def analyze(places: list[dict[str, Any]]) -> list[GoogleSearchResult]:
        analyzed.append(places)
        return [
            GoogleSearchResult(**{**places[0], "place_id": "a"}, website_status="INSECURE",
                               website_issue="no HTTPS; no viewport meta", discovery_method="T"),
            GoogleSearchResult(**{**places[0], "place_id": "b"}, website_status="INSECURE",
                               website_issue="no HTTPS", discovery_method="T"),
        ]

    outcome = collect_new_leads(
        [[_place(place_id="a", website="https://a.fi")]], analyze,
        count=5, filters=SearchFilters(statuses=["not_mobile"]), excluded={},
    )
    assert [r.place_id for r in outcome.results] == ["a"]


def test_excluded_places_are_not_analyzed() -> None:
    analyzed: list[str] = []

    def analyze(places: list[dict[str, Any]]) -> list[GoogleSearchResult]:
        analyzed.extend(p["place_id"] for p in places)
        return [GoogleSearchResult(**p, website_status="NO WEBSITE", discovery_method="T") for p in places]

    page = [_place(place_id=pid, name=pid) for pid in ("a", "b", "c", "d")]
    outcome = collect_new_leads(
        [page], analyze, count=10, filters=SearchFilters(),
        excluded={"a": "in_pipeline", "b": "dismissed", "c": "seen"},
    )
    assert analyzed == ["d"]
    assert outcome.skipped == {"in_pipeline": 1, "dismissed": 1, "seen": 1}


def test_collect_stops_consuming_pages_at_target() -> None:
    consumed: list[int] = []

    def pages() -> Any:
        for n in range(5):
            consumed.append(n)
            yield [_place(place_id=f"p{n}_{i}", name=f"Y{n}{i}") for i in range(3)]

    outcome = collect_new_leads(
        pages(), lambda ps: [GoogleSearchResult(**p, website_status="NO WEBSITE", discovery_method="T") for p in ps],
        count=4, filters=SearchFilters(), excluded={},
    )
    assert consumed == [0, 1]
    assert outcome.target_reached
    assert len(outcome.results) == 4


# --- Migraatio ---

def test_migration_backfills_pipeline_places(tmp_path: Path) -> None:
    backend = Path(__file__).resolve().parent.parent
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        cfg = Config(str(backend / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend / "migrations"))
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "3d717a6775b2")
        conn.execute(text(
            "INSERT INTO lead (user_id, google_place_id, name, city, do_not_contact, pipeline_status, source, "
            "created_at, updated_at) VALUES "
            "('u1', 'ChIJabc', 'A', 'Espoo', 0, 'Shortlisted', 'API', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('u1', 'manual-1', 'B', 'Espoo', 0, 'Shortlisted', 'MANUAL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
            "('u2', NULL, 'C', 'Espoo', 0, 'Shortlisted', 'MANUAL', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        command.upgrade(cfg, "head")
        rows = conn.execute(text("SELECT user_id, place_id, status FROM placestatus")).all()
    engine.dispose()
    assert [tuple(r) for r in rows] == [("u1", "ChIJabc", "in_pipeline")]


def test_creating_lead_marks_place_in_pipeline(client_a: TestClient, make_lead: Any, session: Session) -> None:
    make_lead(google_place_id="ChIJnew1")
    make_lead(google_place_id="manual-99", name="Käsin")
    rows = session.exec(select(PlaceStatus)).all()
    assert [(r.place_id, r.status) for r in rows] == [("ChIJnew1", "in_pipeline")]
    assert session.exec(select(Lead)).all()
