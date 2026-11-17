"""Ostosignaalit liidille: sivun nopeus (PageSpeed Insights) ja sivun ikä (©-vuosi).

Vain mitattu tai sivulla oikeasti luettu arvo tallennetaan. Epäonnistunut mittaus ei jätä arvoa.
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_TIMEOUT_SECONDS = 60

# Core Web Vitals -rajat (LCP sekunteina): hidas > 4 s, nopea < 2,5 s
SLOW_LCP_SECONDS = 4.0
FAST_LCP_SECONDS = 2.5
OLD_SITE_MIN_AGE_YEARS = 3
FEW_REVIEWS_BELOW = 10

_FIRST_YEAR = 1995
_COPYRIGHT_RE = re.compile(r"(?:©|&copy;|\(c\)|copyright)[^0-9]{0,40}((?:19|20)\d{2})(?:\s*[-–—]\s*((?:19|20)\d{2}))?", re.IGNORECASE)


class SpeedTestUnavailable(Exception):
    """PSI ei vastannut (kiintiö, virhe, timeout) eikä arvoa ole."""


@dataclass(frozen=True)
class SpeedResult:
    lcp_seconds: float
    score: int  # Lighthousen suorituskykypisteet 0-100


def is_few_reviews(review_count: Optional[int]) -> bool:
    # Google jättää userRatingCountin pois, kun arvosteluja ei ole -> None = 0
    return (review_count or 0) < FEW_REVIEWS_BELOW


def measure_pagespeed(url: str, api_key: str = "") -> SpeedResult:
    """PageSpeed Insights v5, mobiili. Estävä kutsu: aja asyncio.to_thread():llä."""
    params = {"url": url, "strategy": "mobile", "category": "performance"}
    if api_key:
        params["key"] = api_key
    try:
        response = requests.get(PSI_URL, params=params, timeout=PSI_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise SpeedTestUnavailable(f"PSI request failed: {type(e).__name__}") from e
    if response.status_code != 200:
        raise SpeedTestUnavailable(f"PSI HTTP {response.status_code}")
    try:
        lighthouse = response.json()["lighthouseResult"]
        lcp_ms = lighthouse["audits"]["largest-contentful-paint"]["numericValue"]
        score = lighthouse["categories"]["performance"]["score"]
    except (ValueError, KeyError, TypeError) as e:
        raise SpeedTestUnavailable("PSI response had no LCP") from e
    if not isinstance(lcp_ms, (int, float)) or not isinstance(score, (int, float)) or lcp_ms <= 0:
        raise SpeedTestUnavailable("PSI response had no LCP")
    return SpeedResult(lcp_seconds=round(lcp_ms / 1000, 1), score=round(score * 100))


def extract_copyright_year(soup: BeautifulSoup, now: Optional[datetime] = None) -> Optional[int]:
    """Suurin ©-merkinnän vuosi sivulta (alue 2012-2024 -> 2024). None jos ei selvää merkintää.

    Lukee raakasoupin: footer on yleensä juuri se paikka, jonka Deep Scanin tekstinpoisto karsii.
    """
    current = (now or datetime.now(timezone.utc)).year
    years: list[int] = []
    for match in _COPYRIGHT_RE.finditer(soup.get_text(separator=" ")):
        for raw in match.groups():
            if raw and _FIRST_YEAR <= int(raw) <= current:
                years.append(int(raw))
    return max(years) if years else None


def is_old_site(copyright_year: Optional[int], now: Optional[datetime] = None) -> bool:
    current = (now or datetime.now(timezone.utc)).year
    return copyright_year is not None and current - copyright_year >= OLD_SITE_MIN_AGE_YEARS
