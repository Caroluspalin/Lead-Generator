from dataclasses import dataclass, field
from typing import Any, Callable, Union

import pytest
import requests

from app.utils import website_check as wc
from app.utils.website_check import WebsiteCheck, analyze_website

OK_HTML = '<html><head><title>Parturi</title><meta name="viewport" content="width=device-width"></head><body>Tervetuloa</body></html>'
NO_VIEWPORT_HTML = "<html><head><title>Parturi</title></head><body>Tervetuloa</body></html>"


@dataclass
class _Resp:
    status_code: int = 200
    url: str = "https://example.fi/"
    text: str = OK_HTML
    headers: dict[str, str] = field(default_factory=dict)


Outcome = Union[_Resp, Exception]


class _FakeWeb:
    """Mockattu requests.get: vastaus valitaan (skeema, verify) -parin perusteella."""

    def __init__(self, routes: dict[tuple[str, bool], Union[Outcome, list[Outcome]]]) -> None:
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> _Resp:
        verify = kwargs.get("verify", True)
        self.calls.append({"url": url, **kwargs})
        key = (url.split("://", 1)[0], verify)
        outcome = self.routes[key]
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _FakeWeb]:
    def _install(routes: dict[tuple[str, bool], Union[Outcome, list[Outcome]]]) -> _FakeWeb:
        fake = _FakeWeb(routes)
        monkeypatch.setattr("requests.get", fake)
        return fake

    return _install


def _dns_error() -> requests.exceptions.ConnectionError:
    return requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='x.fi'): Max retries exceeded (Caused by NameResolutionError: "
        "Failed to resolve 'x.fi' ([Errno 8] nodename nor servname provided, or not known))"
    )


def _refused() -> requests.exceptions.ConnectionError:
    return requests.exceptions.ConnectionError("[Errno 61] Connection refused")


def _ssl(msg: str) -> requests.exceptions.SSLError:
    return requests.exceptions.SSLError(msg)


# --- NO WEBSITE ---

@pytest.mark.parametrize("url", [None, "", "   "])
def test_no_website(url: str | None) -> None:
    assert analyze_website(url) == WebsiteCheck("NO WEBSITE")


# --- WEBSITE OK / NOT MOBILE ---

def test_website_ok(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _Resp()})
    assert analyze_website("http://example.fi") == WebsiteCheck("WEBSITE OK")


def test_not_mobile(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _Resp(text=NO_VIEWPORT_HTML)})
    assert analyze_website("example.fi") == WebsiteCheck("NOT MOBILE", "no viewport meta")


def test_viewport_meta_case_insensitive(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _Resp(text='<meta name="Viewport" content="width=device-width">')})
    assert analyze_website("example.fi").status == "WEBSITE OK"


def test_https_tried_first_and_browser_headers_used(web: Callable[..., _FakeWeb]) -> None:
    fake = web({("https", True): _Resp()})
    analyze_website("http://www.example.fi/palvelut?x=1")

    call = fake.calls[0]
    assert call["url"] == "https://www.example.fi/palvelut?x=1"
    assert "Googlebot" not in call["headers"]["User-Agent"]
    assert call["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert call["headers"]["Accept-Language"].startswith("fi")
    assert call["allow_redirects"] is True
    assert call["timeout"] == 8


# --- BROKEN WEBSITE ---

def test_dns_failure_is_broken(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _dns_error()})
    assert analyze_website("eiole.fi") == WebsiteCheck("BROKEN WEBSITE", "DNS not resolving")


def test_connection_refused_on_both_schemes_is_broken(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _refused(), ("http", True): _refused()})
    assert analyze_website("example.fi") == WebsiteCheck("BROKEN WEBSITE", "connection refused")


@pytest.mark.parametrize("code", [404, 410, 500, 502, 503])
def test_broken_http_status(web: Callable[..., _FakeWeb], code: int) -> None:
    web({("https", True): _Resp(status_code=code, text="<html><title>Error</title></html>")})
    assert analyze_website("example.fi") == WebsiteCheck("BROKEN WEBSITE", f"HTTP {code}")


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><h1>This domain is for sale!</h1></body></html>",
        "<html><body>Buy this domain at a great price</body></html>",
        "<html><body>Tämä verkkotunnus on myytävänä</body></html>",
        "<html><body><script src='//www.sedoparking.com/x.js'></script></body></html>",
    ],
)
def test_parked_domain_markers(web: Callable[..., _FakeWeb], html: str) -> None:
    web({("https", True): _Resp(text=html)})
    assert analyze_website("example.fi") == WebsiteCheck("BROKEN WEBSITE", "parked domain")


def test_redirect_to_parking_host(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _Resp(url="https://www.hugedomains.com/domain_profile.cfm?d=example.fi", text=OK_HTML)})
    assert analyze_website("example.fi") == WebsiteCheck("BROKEN WEBSITE", "parked domain")


def test_parked_domain_with_bad_ssl_is_broken_not_insecure(web: Callable[..., _FakeWeb]) -> None:
    web({
        ("https", True): _ssl("certificate verify failed: Hostname mismatch, certificate is not valid for 'example.fi'"),
        ("https", False): _Resp(text="<p>This domain may be for sale</p>"),
    })
    assert analyze_website("example.fi") == WebsiteCheck("BROKEN WEBSITE", "parked domain")


# --- INSECURE ---

def test_expired_ssl_is_insecure(web: Callable[..., _FakeWeb]) -> None:
    web({
        ("https", True): _ssl("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired"),
        ("https", False): _Resp(),
    })
    assert analyze_website("example.fi") == WebsiteCheck("INSECURE", "SSL certificate expired")


def test_hostname_mismatch_ssl_is_insecure(web: Callable[..., _FakeWeb]) -> None:
    web({
        ("https", True): _ssl("certificate verify failed: Hostname mismatch, certificate is not valid for 'x.fi'"),
        ("https", False): _Resp(),
    })
    assert analyze_website("x.fi") == WebsiteCheck("INSECURE", "SSL certificate hostname mismatch")


def test_http_only_site_is_insecure(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _refused(), ("http", True): _Resp(url="http://example.fi/")})
    assert analyze_website("example.fi") == WebsiteCheck("INSECURE", "no HTTPS")


def test_https_redirecting_to_http_is_insecure(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _Resp(url="http://example.fi/")})
    assert analyze_website("example.fi") == WebsiteCheck("INSECURE", "redirects to HTTP")


def test_insecure_and_not_mobile_keeps_both_reasons(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _refused(), ("http", True): _Resp(url="http://example.fi/", text=NO_VIEWPORT_HTML)})
    assert analyze_website("example.fi") == WebsiteCheck("INSECURE", "no HTTPS; no viewport meta")


def test_http_fallback_redirecting_to_https_is_ok(web: Callable[..., _FakeWeb]) -> None:
    # HTTPS-pyyntö kaatui hetkellisesti, HTTP ohjaa toimivaan HTTPS:ään
    web({("https", True): _refused(), ("http", True): _Resp(url="https://example.fi/")})
    assert analyze_website("example.fi") == WebsiteCheck("WEBSITE OK")


# --- UNKNOWN ---

@pytest.mark.parametrize("code", [401, 403, 429])
def test_bot_block_status_is_unknown(web: Callable[..., _FakeWeb], code: int) -> None:
    web({("https", True): _Resp(status_code=code)})
    assert analyze_website("example.fi") == WebsiteCheck("UNKNOWN", f"HTTP {code}")


def test_cloudflare_challenge_is_unknown_even_with_503(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _Resp(status_code=503, text="<html><head><title>Just a moment...</title></head></html>")})
    assert analyze_website("example.fi") == WebsiteCheck("UNKNOWN", "bot protection")


def test_cf_mitigated_header_is_unknown(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _Resp(headers={"cf-mitigated": "challenge"})})
    assert analyze_website("example.fi").status == "UNKNOWN"


def test_recaptcha_on_normal_page_is_not_bot_block(web: Callable[..., _FakeWeb]) -> None:
    html = OK_HTML.replace("</body>", "<script src='https://www.google.com/recaptcha/api.js'></script>"
                           "<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></body>")
    web({("https", True): _Resp(text=html)})
    assert analyze_website("example.fi").status == "WEBSITE OK"


def test_timeout_is_retried_once_then_unknown(web: Callable[..., _FakeWeb]) -> None:
    fake = web({
        ("https", True): [requests.exceptions.ReadTimeout(), requests.exceptions.ReadTimeout()],
        ("http", True): [requests.exceptions.ConnectTimeout(), requests.exceptions.ConnectTimeout()],
    })
    assert analyze_website("example.fi") == WebsiteCheck("UNKNOWN", "timeout")
    assert [c["url"].split(":")[0] for c in fake.calls] == ["https", "https", "http", "http"]


def test_timeout_then_success_on_retry(web: Callable[..., _FakeWeb]) -> None:
    fake = web({("https", True): [requests.exceptions.ReadTimeout(), _Resp()]})
    assert analyze_website("example.fi") == WebsiteCheck("WEBSITE OK")
    assert len(fake.calls) == 2


def test_other_4xx_is_unknown_not_broken(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _Resp(status_code=406)})
    assert analyze_website("example.fi") == WebsiteCheck("UNKNOWN", "HTTP 406")


def test_constants_match_expected_values() -> None:
    assert wc.TIMEOUT_SECONDS == 8
    assert wc.TIMEOUT_RETRIES == 1


# --- Somesivu ---

@pytest.mark.parametrize(
    "url",
    [
        "https://www.facebook.com/T%C3%A4hti-Paplari-240400222678777/",
        "http://facebook.com/parturi",
        "https://m.facebook.com/parturi",
        "facebook.com/parturi",
        "https://fb.com/parturi",
        "https://fb.me/parturi",
        "https://www.instagram.com/parturi/",
        "instagram.com/parturi",
        "https://linktr.ee/parturi",
        "HTTPS://WWW.FACEBOOK.COM/Parturi",
    ],
)
def test_social_media_url_is_no_website_without_request(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("requests.get", lambda u, **_k: calls.append(u))
    assert analyze_website(url) == WebsiteCheck("NO WEBSITE", "social media only")
    assert calls == []


@pytest.mark.parametrize(
    "url",
    ["https://notfacebook.com/", "https://facebook.com.example.fi/", "https://parturi-instagram.fi/"],
)
def test_lookalike_domains_are_not_social_media(url: str, web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _Resp(url=url)})
    assert analyze_website(url).status == "WEBSITE OK"


# --- fetch_page (yhteystietohaku käyttää samoja sääntöjä) ---

def test_fetch_page_uses_https_and_browser_headers(web: Callable[..., _FakeWeb]) -> None:
    fake = web({("https", True): _Resp()})
    assert wc.fetch_page("http://example.fi/yhteystiedot") is not None
    assert fake.calls[0]["url"] == "https://example.fi/yhteystiedot"
    assert fake.calls[0]["headers"] is wc.HEADERS
    assert fake.calls[0]["timeout"] == wc.TIMEOUT_SECONDS


def test_fetch_page_falls_back_on_bad_ssl_and_http(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _ssl("certificate has expired"), ("https", False): _Resp(text="ssl-ohitus")})
    page = wc.fetch_page("example.fi")
    assert page is not None and page.text == "ssl-ohitus"

    web({("https", True): _refused(), ("http", True): _Resp(url="http://example.fi/", text="http")})
    page = wc.fetch_page("example.fi")
    assert page is not None and page.text == "http"


def test_fetch_page_never_requests_social_media(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("requests.get", lambda u, **_k: calls.append(u))
    assert wc.fetch_page("https://www.facebook.com/parturi") is None
    assert calls == []


def test_fetch_page_dns_failure_is_none(web: Callable[..., _FakeWeb]) -> None:
    web({("https", True): _dns_error()})
    assert wc.fetch_page("eiole.fi") is None
