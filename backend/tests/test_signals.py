"""Ostosignaalit: PageSpeed-mittaus (mockattu), ©-vuosi, Few reviews -suodatin ja sähköpostiprompti."""
from datetime import datetime, timezone
from typing import Any

import pytest
import requests
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import build_demo_email_user_prompt, measured_speed_line
from app.models import Lead, SenderProfile
from app.utils import signals
from app.utils.signals import (
    SpeedResult,
    SpeedTestUnavailable,
    extract_copyright_year,
    is_few_reviews,
    is_old_site,
    measure_pagespeed,
)

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _psi(lcp_ms: float = 8200, score: float = 0.31) -> dict[str, Any]:
    return {"lighthouseResult": {
        "audits": {"largest-contentful-paint": {"numericValue": lcp_ms}},
        "categories": {"performance": {"score": score}},
    }}


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# --- PSI ---

def test_measure_pagespeed_parses_lcp_and_score(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_get(url: str, params: dict[str, str], timeout: int) -> FakeResponse:
        seen.update(params=params, timeout=timeout)
        return FakeResponse(200, _psi())

    monkeypatch.setattr(signals.requests, "get", fake_get)
    assert measure_pagespeed("https://a.fi", "") == SpeedResult(lcp_seconds=8.2, score=31)
    assert seen["params"]["strategy"] == "mobile"
    assert "key" not in seen["params"]
    assert seen["timeout"] == signals.PSI_TIMEOUT_SECONDS


def test_measure_pagespeed_sends_key_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(signals.requests, "get", lambda url, params, timeout: (seen.update(params=params), FakeResponse(200, _psi()))[1])
    measure_pagespeed("https://a.fi", "AIza-test")
    assert seen["params"]["key"] == "AIza-test"


@pytest.mark.parametrize("response", [
    FakeResponse(429, {}),
    FakeResponse(500, {}),
    FakeResponse(200, {"lighthouseResult": {}}),
    FakeResponse(200, ValueError("not json")),
    FakeResponse(200, _psi(lcp_ms=0)),
])
def test_measure_pagespeed_failures_raise(monkeypatch: pytest.MonkeyPatch, response: FakeResponse) -> None:
    monkeypatch.setattr(signals.requests, "get", lambda url, params, timeout: response)
    with pytest.raises(SpeedTestUnavailable):
        measure_pagespeed("https://a.fi")


def test_measure_pagespeed_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, params: dict[str, str], timeout: int) -> FakeResponse:
        raise requests.Timeout()

    monkeypatch.setattr(signals.requests, "get", boom)
    with pytest.raises(SpeedTestUnavailable):
        measure_pagespeed("https://a.fi")


# --- Endpoint ---

def test_measure_speed_endpoint_stores_values(
    client_a: TestClient, make_lead: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead = make_lead(website="https://a.fi", website_status="NOT MOBILE")
    monkeypatch.setattr("app.main.measure_pagespeed", lambda url, key: SpeedResult(8.2, 31))
    monkeypatch.setattr("app.main.fetch_copyright_year", lambda url: 2017)
    res = client_a.post(f"/leads/{lead['id']}/measure-speed")
    assert res.status_code == 200
    body = res.json()
    assert body["pagespeed_lcp_s"] == 8.2
    assert body["pagespeed_score"] == 31
    assert body["pagespeed_at"] is not None
    assert body["site_copyright_year"] == 2017


def test_measure_speed_failure_stores_nothing(
    client_a: TestClient, make_lead: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead = make_lead(website="https://a.fi", website_status="WEBSITE OK")

    def unavailable(url: str, key: str) -> SpeedResult:
        raise SpeedTestUnavailable("PSI HTTP 429")

    monkeypatch.setattr("app.main.measure_pagespeed", unavailable)
    res = client_a.post(f"/leads/{lead['id']}/measure-speed")
    assert res.status_code == 503
    assert res.json()["detail"] == "Speed test unavailable, try later"
    stored = next(l for l in client_a.get("/leads").json() if l["id"] == lead["id"])
    assert stored["pagespeed_lcp_s"] is None and stored["pagespeed_at"] is None


@pytest.mark.parametrize("fields", [
    {},
    {"website": "https://facebook.com/x", "website_status": "NO WEBSITE"},
    {"website": "https://a.fi", "website_status": "BROKEN WEBSITE"},
])
def test_measure_speed_needs_working_website(client_a: TestClient, make_lead: Any, fields: dict[str, str]) -> None:
    lead = make_lead(**fields)
    assert client_a.post(f"/leads/{lead['id']}/measure-speed").status_code == 422


def test_measure_speed_other_users_lead_is_404(client_a: TestClient, client_b: TestClient, make_lead: Any) -> None:
    lead = make_lead(website="https://a.fi", website_status="WEBSITE OK")
    assert client_b.post(f"/leads/{lead['id']}/measure-speed").status_code == 404


# --- ©-vuosi ---

@pytest.mark.parametrize("html,expected", [
    ("<footer>© 2017 Parturi Oy</footer>", 2017),
    ("<footer>Copyright 2012 - 2019 Parturi</footer>", 2019),
    ("<footer>&copy; 2015-2021</footer>", 2021),
    ("<footer>(c) 2009 Salon</footer>", 2009),
    ("<p>Perustettu 1998. Hinta 2020 €</p>", None),
    ("<footer>© 2090 Tulevaisuus</footer>", None),
    ("<footer>© Parturi Oy</footer>", None),
])
def test_extract_copyright_year(html: str, expected: int | None) -> None:
    assert extract_copyright_year(_soup(html), NOW) == expected


def test_old_site_threshold() -> None:
    assert is_old_site(2023, NOW)
    assert not is_old_site(2024, NOW)
    assert not is_old_site(None, NOW)


def test_few_reviews_threshold() -> None:
    assert is_few_reviews(None) and is_few_reviews(0) and is_few_reviews(9)
    assert not is_few_reviews(10)


# --- Few reviews -suodatin hakuun ---

def test_search_few_reviews_filter(client_a: TestClient) -> None:
    res = client_a.get("/search", params={
        "business_type": "parturi", "city": "Kauniainen", "few_reviews": "true", "only_new": "false",
    })
    assert res.status_code == 200
    results = res.json()["results"]
    assert results
    assert all((r["review_count"] or 0) < 10 for r in results)


# --- Sähköpostiprompti ---

def _profile() -> SenderProfile:
    return SenderProfile(user_id="u", name="Palin", short_intro="teen nettisivuja")


def test_speed_line_only_when_measured_and_slow() -> None:
    assert measured_speed_line(Lead(user_id="u", name="A", city="B")) is None
    assert measured_speed_line(Lead(user_id="u", name="A", city="B", pagespeed_lcp_s=3.1)) is None
    line = measured_speed_line(Lead(user_id="u", name="A", city="B", pagespeed_lcp_s=8.2))
    assert line is not None and "8,2" in line


def test_demo_prompt_mentions_speed_only_when_measured() -> None:
    plain = Lead(user_id="u", name="A", city="Espoo", website_status="WEBSITE OK", site_copyright_year=2015)
    prompt = build_demo_email_user_prompt(plain, _profile())
    assert "LATAUSAIKA" not in prompt and "2015" not in prompt
    assert "Kirjoita vain kappale 1." in prompt

    measured = Lead(user_id="u", name="A", city="Espoo", website_status="WEBSITE OK",
                    pagespeed_lcp_s=8.2, site_copyright_year=2015)
    prompt = build_demo_email_user_prompt(measured, _profile())
    assert "8,2 sekunnissa" in prompt
    assert "2015" not in prompt
    assert "Kirjoita kappaleet 1 ja 2." in prompt
