"""Sähköpostiosoitteen haku yrityksen omalta sivustolta.

Rajat: etusivu + enintään MAX_CONTACT_PAGES todennäköistä yhteystietosivua samalta
sivustolta. Ei muuta crawlausta, ei osoitteiden arvailua (ei "info@domain"-oletuksia)
eikä ulkoisia hakupalveluita: vain sivulla oikeasti näkyvä osoite kelpaa.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from .website_check import fetch_page

logger = logging.getLogger(__name__)

MAX_CONTACT_PAGES = 3

# Linkin teksti tai polku (pienillä, ilman ääkkösiä tai niiden kanssa)
CONTACT_KEYWORDS = (
    "yhteystiedot", "yhteystieto", "ota-yhteytta", "ota yhteyttä", "otayhteytta",
    "yhteydenotto", "yhteys", "contact", "kontakt", "kontakti", "kontakta",
)

# Yleiset osoitteet ovat varmempia kuin henkilön oma (henkilö voi vaihtua)
GENERIC_LOCAL_PARTS = (
    "info", "asiakaspalvelu", "myynti", "toimisto", "ajanvaraus", "varaukset", "posti",
    "contact", "hello", "hei", "moi", "office", "tilaukset", "palvelu", "yhteys",
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")

# "nimi(at)domain.fi", "nimi [at] domain.fi", "nimi (ät) domain (dot) fi"
_AT_RE = re.compile(r"\s*[\(\[\{]\s*(?:at|ät|miuku)\s*[\)\]\}]\s*", re.IGNORECASE)
_DOT_RE = re.compile(r"\s*[\(\[\{]\s*(?:dot|piste)\s*[\)\]\}]\s*", re.IGNORECASE)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".bmp", ".ico")
EXAMPLE_DOMAINS = (
    "example.com", "example.fi", "example.org", "example.net", "domain.fi", "domain.com",
    "yourdomain.com", "sinundomain.fi", "esimerkki.fi", "email.com", "test.com",
    "sentry.io", "wixpress.com", "sentry-next.wixpress.com",
)
EXAMPLE_LOCAL_PARTS = ("nimi", "etunimi.sukunimi", "name", "firstname.lastname", "user", "your", "you", "test", "email", "sahkoposti")
NO_REPLY_RE = re.compile(r"^(no-?reply|do-?not-?reply|mailer-daemon)", re.IGNORECASE)


@dataclass(frozen=True)
class ContactEmail:
    email: str
    source: str  # esim. "mailto on /yhteystiedot"


@dataclass(frozen=True)
class _Candidate:
    email: str
    method: str
    path: str
    order: int


def _site_domain(url: str) -> str:
    host = (urlparse(url if "://" in url else f"//{url}").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_valid(email: str) -> bool:
    email = email.lower()
    local, _, domain = email.rpartition("@")
    if not local or not domain or "." not in domain:
        return False
    if domain.endswith(IMAGE_EXTENSIONS) or email.endswith(IMAGE_EXTENSIONS):
        return False
    if any(domain == d or domain.endswith("." + d) for d in EXAMPLE_DOMAINS):
        return False
    if local in EXAMPLE_LOCAL_PARTS or NO_REPLY_RE.match(local):
        return False
    return True


def _decode_cloudflare(encoded: str) -> Optional[str]:
    """Cloudflare Email Obfuscation: hex, ensimmäinen tavu on XOR-avain."""
    try:
        data = bytes.fromhex(encoded)
    except ValueError:
        return None
    if len(data) < 2:
        return None
    key = data[0]
    return "".join(chr(b ^ key) for b in data[1:])


def deobfuscate(text: str) -> str:
    return _DOT_RE.sub(".", _AT_RE.sub("@", text))


def extract_emails(html: str) -> list[tuple[str, str]]:
    """Palauttaa [(email, method)] löytöjärjestyksessä. method: mailto | cloudflare | text | obfuscated."""
    soup = BeautifulSoup(html, "html.parser")
    found: list[tuple[str, str]] = []

    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if href.lower().startswith("mailto:"):
            address = unquote(href[7:].split("?", 1)[0]).strip()
            for part in address.split(","):
                found.append((part.strip(), "mailto"))
        if "/cdn-cgi/l/email-protection#" in href:
            decoded = _decode_cloudflare(href.rsplit("#", 1)[1])
            if decoded:
                found.append((decoded, "cloudflare"))

    for el in soup.select("[data-cfemail]"):
        decoded = _decode_cloudflare(str(el.get("data-cfemail", "")))
        if decoded:
            found.append((decoded, "cloudflare"))

    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(" ")
    for match in EMAIL_RE.findall(text):
        found.append((match, "text"))
    plain = set(EMAIL_RE.findall(text))
    for match in EMAIL_RE.findall(deobfuscate(text)):
        if match not in plain:
            found.append((match, "obfuscated"))

    return [(e.strip(".").lower(), m) for e, m in found if _is_valid(e.strip("."))]


def find_contact_links(html: str, page_url: str) -> list[str]:
    """Enintään MAX_CONTACT_PAGES samalla sivustolla olevaa yhteystietolinkkiä."""
    soup = BeautifulSoup(html, "html.parser")
    site = _site_domain(page_url)
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(page_url, href).split("#", 1)[0]
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or _site_domain(absolute) != site:
            continue
        haystack = f"{a.get_text(' ', strip=True)} {unquote(parsed.path)}".lower()
        if any(k in haystack for k in CONTACT_KEYWORDS) and absolute not in links:
            if absolute.rstrip("/") != page_url.rstrip("/"):
                links.append(absolute)
        if len(links) >= MAX_CONTACT_PAGES:
            break
    return links


def _rank(candidate: _Candidate, site: str) -> tuple[int, int, int]:
    local, _, domain = candidate.email.partition("@")
    own_domain = domain == site or domain.endswith("." + site)
    generic = local in GENERIC_LOCAL_PARTS
    # Pienempi = parempi: oma domain, yleinen osoite, löytöjärjestys
    return (0 if own_domain else 1, 0 if generic else 1, candidate.order)


def pick_best(candidates: list[_Candidate], site: str) -> Optional[_Candidate]:
    return min(candidates, key=lambda c: _rank(c, site)) if candidates else None


def find_contact_email(website: str) -> Optional[ContactEmail]:
    """Blokkaava: aja asyncio.to_thread():ssä."""
    home = fetch_page(website)
    if home is None or home.status_code >= 400:
        return None

    pages: list[tuple[str, str]] = [(home.url, home.text)]
    for link in find_contact_links(home.text, home.url):
        response = fetch_page(link)
        if response is not None and response.status_code < 400:
            pages.append((response.url, response.text))

    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for page_url, html in pages:
        path = urlparse(page_url).path or "/"
        for email, method in extract_emails(html):
            if email in seen:
                continue
            seen.add(email)
            candidates.append(_Candidate(email, method, path, len(candidates)))

    best = pick_best(candidates, _site_domain(home.url))
    if best is None:
        logger.info(f"Sähköpostia ei löytynyt: {website} ({len(pages)} sivua)")
        return None
    return ContactEmail(best.email, f"{best.method} on {best.path}")
