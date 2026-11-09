"""Yrityksen nettisivun tekninen tila myyntiperusteeksi.

Tärkein sääntö: epävarma tulos (bottiesto, 401/403, timeout) on UNKNOWN, ei BROKEN.
Väärä "sivusi on rikki" -väite pilaa myyntiviestin ja pisteytyksen.
"""
import logging
import re
import warnings
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

NO_WEBSITE = "NO WEBSITE"
BROKEN_WEBSITE = "BROKEN WEBSITE"
INSECURE = "INSECURE"
NOT_MOBILE = "NOT MOBILE"
WEBSITE_OK = "WEBSITE OK"
UNKNOWN = "UNKNOWN"

TIMEOUT_SECONDS = 8
TIMEOUT_RETRIES = 1

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fi,en;q=0.8",
}

# Pelkkä somesivu ei ole oma nettisivu -> NO WEBSITE. Näihin ei tehdä pyyntöä lainkaan.
SOCIAL_MEDIA_HOSTS = ("facebook.com", "fb.com", "fb.me", "instagram.com", "linktr.ee")
SOCIAL_MEDIA_ISSUE = "social media only"
# Ajanvarausalusta ei myöskään ole oma sivu: NO WEBSITE, ja osoite toimii demossa varauslinkkinä
BOOKING_HOSTS = ("timma.fi", "varaa.com", "vello.fi", "slotti.fi", "fresha.com")
BOOKING_ISSUE = "booking platform only"

BROKEN_HTTP_STATUSES = {404, 410}
BOT_BLOCK_HTTP_STATUSES = {401, 403, 429}

# Parkkisivut / myynnissä olevat domainit: tunnetut parkkipalvelut ja yleiset tekstit
PARKING_HOSTS = (
    "sedo.com", "sedoparking.com", "dan.com", "afternic.com", "hugedomains.com",
    "parkingcrew.net", "bodis.com", "above.com", "undeveloped.com", "parklogic.com",
    "domainmarket.com", "buydomains.com", "uniregistry.com", "skenzo.com",
)
PARKING_MARKERS = (
    "this domain is for sale",
    "this domain may be for sale",
    "domain is for sale",
    "buy this domain",
    "the domain name is for sale",
    "domain for sale",
    "is parked free",
    "domain parking",
    "parked domain",
    "sedoparking",
    "parkingcrew",
    "bodis.com",
    "verkkotunnus on myynnissä",
    "tämä verkkotunnus on myytävänä",
    "verkkotunnus on varattu",
)
# Vain haastesivun <title>: reCAPTCHA-lomakkeet ja Cloudflaren challenge-platform-skripti
# ovat yleisiä myös täysin toimivilla sivuilla, joten niitä ei käytetä merkkinä
BOT_CHALLENGE_TITLES = (
    "just a moment...",
    "attention required! | cloudflare",
    "ddos-guard",
    "access denied",
)


@dataclass(frozen=True)
class WebsiteCheck:
    status: str
    issue: Optional[str] = None


class _Failure(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind  # dns | refused | timeout | ssl | other
        self.detail = detail


def _classify_exception(exc: requests.RequestException) -> _Failure:
    text = str(exc).lower()
    if isinstance(exc, requests.exceptions.SSLError):
        if "expired" in text:
            return _Failure("ssl", "SSL certificate expired")
        if "hostname" in text or "doesn't match" in text or "not valid for" in text:
            return _Failure("ssl", "SSL certificate hostname mismatch")
        if "self-signed" in text or "self signed" in text:
            return _Failure("ssl", "SSL certificate self-signed")
        return _Failure("ssl", "SSL certificate invalid")
    if isinstance(exc, requests.exceptions.Timeout):
        return _Failure("timeout", "timeout")
    if isinstance(exc, requests.exceptions.ConnectionError):
        dns_markers = (
            "nameresolutionerror", "name or service not known", "nodename nor servname",
            "getaddrinfo failed", "temporary failure in name resolution", "no address associated",
            "failed to resolve",
        )
        if any(m in text for m in dns_markers):
            return _Failure("dns", "DNS not resolving")
        if "refused" in text:
            return _Failure("refused", "connection refused")
        return _Failure("other", "connection failed")
    return _Failure("other", "request failed")


def _get(url: str, *, verify: bool = True) -> requests.Response:
    """GET uudelleenohjauksia seuraten, yksi uudelleenyritys timeoutille."""
    last: Optional[requests.RequestException] = None
    for _ in range(1 + TIMEOUT_RETRIES):
        try:
            if verify:
                return requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS, allow_redirects=True)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
                return requests.get(
                    url, headers=HEADERS, timeout=TIMEOUT_SECONDS, allow_redirects=True, verify=False
                )
        except requests.exceptions.Timeout as e:
            last = e
            continue
        except requests.RequestException as e:
            raise _classify_exception(e) from e
    assert last is not None
    raise _classify_exception(last) from last


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_social_media_url(url: str) -> bool:
    host = _host(url if "://" in url else f"//{url}")
    return any(host == h or host.endswith("." + h) for h in SOCIAL_MEDIA_HOSTS)


def is_booking_url(url: Optional[str]) -> bool:
    if not url:
        return False
    host = _host(url if "://" in url else f"//{url}")
    return any(host == h or host.endswith("." + h) for h in BOOKING_HOSTS)


def _is_parked(response: requests.Response) -> bool:
    final_host = _host(response.url)
    if any(final_host == h or final_host.endswith("." + h) for h in PARKING_HOSTS):
        return True
    text = response.text[:200_000].lower()
    return any(marker in text for marker in PARKING_MARKERS)


def _is_bot_challenge(response: requests.Response, soup: BeautifulSoup) -> bool:
    if response.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    title = soup.title.get_text(strip=True).lower() if soup.title else ""
    return title in BOT_CHALLENGE_TITLES


def _has_viewport(soup: BeautifulSoup) -> bool:
    return soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)}) is not None


def _classify_response(response: requests.Response, *, insecure_issue: Optional[str]) -> WebsiteCheck:
    code = response.status_code
    soup = BeautifulSoup(response.text, "html.parser")

    if code in BOT_BLOCK_HTTP_STATUSES or _is_bot_challenge(response, soup):
        reason = "bot protection" if code not in BOT_BLOCK_HTTP_STATUSES else f"HTTP {code}"
        return WebsiteCheck(UNKNOWN, reason)
    if code in BROKEN_HTTP_STATUSES or code >= 500:
        return WebsiteCheck(BROKEN_WEBSITE, f"HTTP {code}")
    if code >= 400:
        return WebsiteCheck(UNKNOWN, f"HTTP {code}")
    if _is_parked(response):
        return WebsiteCheck(BROKEN_WEBSITE, "parked domain")

    mobile = _has_viewport(soup)
    if insecure_issue:
        issue = insecure_issue if mobile else f"{insecure_issue}; no viewport meta"
        return WebsiteCheck(INSECURE, issue)
    if not mobile:
        return WebsiteCheck(NOT_MOBILE, "no viewport meta")
    return WebsiteCheck(WEBSITE_OK)


def _with_scheme(url: str, scheme: str) -> str:
    parsed = urlparse(url if "://" in url else f"//{url}")
    rest = parsed.netloc + (parsed.path or "/")
    if parsed.query:
        rest += f"?{parsed.query}"
    return f"{scheme}://{rest}"


def analyze_website(url: Optional[str]) -> WebsiteCheck:
    if not url or not url.strip():
        return WebsiteCheck(NO_WEBSITE)
    url = url.strip()
    if is_social_media_url(url):
        return WebsiteCheck(NO_WEBSITE, SOCIAL_MEDIA_ISSUE)
    if is_booking_url(url):
        return WebsiteCheck(NO_WEBSITE, BOOKING_ISSUE)

    # 1) HTTPS ensin (moni Google-websiteUri on http:// vaikka https toimii)
    https_url = _with_scheme(url, "https")
    try:
        response = _get(https_url)
    except _Failure as https_fail:
        if https_fail.kind == "ssl":
            # Palvelin vastaa, mutta sertifikaatti on huono: katsotaan silti sisältö
            # (parkkisivu tai 404 on BROKEN, ei vain INSECURE)
            try:
                response = _get(https_url, verify=False)
            except _Failure:
                return WebsiteCheck(INSECURE, https_fail.detail)
            return _classify_response(response, insecure_issue=https_fail.detail)
        if https_fail.kind == "dns":
            return WebsiteCheck(BROKEN_WEBSITE, https_fail.detail)

        # 2) HTTPS ei vastaa (refused/timeout/muu): toimiiko pelkkä HTTP?
        try:
            response = _get(_with_scheme(url, "http"))
        except _Failure as http_fail:
            if https_fail.kind == "timeout" or http_fail.kind == "timeout":
                return WebsiteCheck(UNKNOWN, "timeout")
            return WebsiteCheck(BROKEN_WEBSITE, http_fail.detail)
        insecure = "no HTTPS" if urlparse(response.url).scheme == "http" else None
        return _classify_response(response, insecure_issue=insecure)

    # HTTPS ohjasi takaisin HTTP:lle -> sivu toimii käytännössä vain ilman salausta
    insecure = "redirects to HTTP" if urlparse(response.url).scheme == "http" else None
    return _classify_response(response, insecure_issue=insecure)


def fetch_page(url: str) -> Optional[requests.Response]:
    """Hakee sivun samoilla säännöillä kuin analyze_website (UA, timeout, retry, SSL/HTTP-fallback).

    Palauttaa None jos sivu ei vastaa. Ei tee pyyntöä someosoitteisiin.
    """
    if not url or is_social_media_url(url) or is_booking_url(url):
        return None
    https_url = url if url.lower().startswith("https://") else _with_scheme(url, "https")
    try:
        return _get(https_url)
    except _Failure as fail:
        if fail.kind == "ssl":
            try:
                return _get(https_url, verify=False)
            except _Failure:
                return None
        if fail.kind == "dns":
            return None
    try:
        return _get(_with_scheme(url, "http"))
    except _Failure:
        return None
