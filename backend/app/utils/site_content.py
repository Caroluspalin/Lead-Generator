"""Yrityksen nykyisen sivuston sisältö demoa varten: palvelut, hinnat ja esittelyteksti.

Rajat:
- etusivu + enintään MAX_SUBPAGES alasivua samalta sivustolta (palvelut, hinnasto, meistä)
- robots.txt:tä noudatetaan: estetty sivu jätetään hakematta, estetty etusivu = ei skannausta
- REQUEST_DELAY_SECONDS viive pyyntöjen välillä (tai robots.txt:n Crawl-delay, max MAX_CRAWL_DELAY)
- kuvia ei koskaan poimita: img/picture/video/source poistetaan ennen tekstin lukua

Rakenteistus (palvelut, hinnat, esittely) tehdään AI:lla main.py:ssä; tämä moduuli antaa sivujen
tekstit ja tarkistaa AI:n vastauksen niitä vasten (verify_site_facts): hinta kelpaa vain jos sen
luvut ja valuutta lukevat samalla sivulla palvelun nimen lähellä.
"""
import logging
import re
import time
import warnings
from dataclasses import dataclass
from typing import Optional
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

USER_AGENT = "AgencyHunter"
HEADERS = {
    "User-Agent": f"Mozilla/5.0 (compatible; {USER_AGENT}/1.0)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fi,en;q=0.5",
}
TIMEOUT_SECONDS = 8
REQUEST_DELAY_SECONDS = 1.0
MAX_CRAWL_DELAY = 5.0
MAX_SUBPAGES = 3
MAX_PAGE_CHARS = 4000
MIN_PAGE_CHARS = 30  # hinnasto voi olla lyhyt: "Leikkaus 32 €, Parta 25 €"
HOMEPAGE_CONTEXT_CHARS = 2000  # Lead.website_context (sama raja kuin vanhalla Deep Scanilla)

# Laajennettu skannaus vain näille: sivu vastaa ainakin osittain ja siitä tehdään uutta sivua
SCAN_STATUSES = {"BROKEN WEBSITE", "INSECURE", "NOT MOBILE"}
# Rikki-tilat, joissa sivulla ei ole yrityksen omaa sisältöä
_NO_CONTENT_ISSUES = ("parked domain", "DNS not resolving", "connection refused", "connection failed")

# Alasivun luokka -> avainsanat linkin polussa tai tekstissä (järjestys = etusijajärjestys)
SUBPAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "prices": ("hinnasto", "hinnat", "hinta", "prices", "pricing", "price"),
    "services": ("palvelut", "palvelu", "hoidot", "hoito", "tuotteet", "ruokalista", "menu", "lounas", "services"),
    "about": ("meista", "meistä", "yritys", "tietoa", "esittely", "about"),
}
_SKIP_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".doc", ".docx")
_REMOVE_TAGS = (
    "script", "style", "nav", "header", "footer", "iframe", "noscript", "svg", "form",
    "img", "picture", "video", "audio", "source", "figure", "canvas",
)


@dataclass(frozen=True)
class SitePage:
    kind: str  # home | services | prices | about
    url: str
    text: str


@dataclass(frozen=True)
class SiteScan:
    pages: list[SitePage]
    blocked: list[str]  # robots.txt:n estämät osoitteet (lokiin ja testeihin)

    @property
    def homepage_text(self) -> Optional[str]:
        home = next((p for p in self.pages if p.kind == "home"), None)
        return home.text[:HOMEPAGE_CONTEXT_CHARS] if home else None


class SiteService(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=60)
    price: Optional[str] = Field(default=None, max_length=24)


class SiteFacts(BaseModel):
    """Tallennetaan Lead.website_facts-sarakkeeseen. Tyhjä = skannattu, mutta ei käyttökelpoista."""
    services: list[SiteService] = Field(default_factory=list, max_length=20)
    about: Optional[str] = Field(default=None, max_length=700)
    pages: list[str] = Field(default_factory=list)  # luetut osoitteet

    @property
    def has_content(self) -> bool:
        return bool(self.services or self.about)

    @property
    def has_prices(self) -> bool:
        return any(s.price for s in self.services)


def should_scan(website: Optional[str], website_status: Optional[str], website_issue: Optional[str]) -> bool:
    if not website or website_status not in SCAN_STATUSES:
        return False
    return not any(marker in (website_issue or "") for marker in _NO_CONTENT_ISSUES)


# --- Haku ---

def _site_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _with_scheme(url: str) -> str:
    return url if "://" in url else f"https://{url}"


def _get(url: str) -> Optional[requests.Response]:
    """GET; huono sertifikaatti (INSECURE-sivut) luetaan ilman tarkistusta, https -> http jos ei vastaa."""
    try:
        return requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS, allow_redirects=True)
    except requests.exceptions.SSLError:
        # Sama periaate kuin website_checkissä: INSECURE-sivun julkinen teksti luetaan ilman
        # sertifikaattitarkistusta, eikä sivulle lähetetä mitään (ei evästeitä, tunnuksia tai lomakkeita)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
                return requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS, allow_redirects=True, verify=False)
        except requests.RequestException:
            return None
    except requests.RequestException:
        if url.startswith("https://"):
            try:
                return requests.get("http://" + url[len("https://"):], headers=HEADERS, timeout=TIMEOUT_SECONDS, allow_redirects=True)
            except requests.RequestException:
                return None
        return None


class _Politeness:
    """robots.txt + viive. Yksi instanssi per sivusto."""

    def __init__(self, base_url: str) -> None:
        self.parser: Optional[robotparser.RobotFileParser] = None
        self.disallow_all = False
        self.delay = REQUEST_DELAY_SECONDS
        self._last: Optional[float] = None
        self._load(base_url)

    def _load(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        response = self._fetch(robots_url)
        if response is None or response.status_code >= 500:
            # Ei vastausta / palvelinvirhe: varovainen tulkinta (kuten Google): ei hakuja
            self.disallow_all = True
            return
        if response.status_code in (401, 403):
            self.disallow_all = True
            return
        if response.status_code >= 400:
            return  # ei robots.txt:tä -> kaikki sallittu
        parser = robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        self.parser = parser
        crawl_delay = parser.crawl_delay(USER_AGENT)
        if crawl_delay:
            self.delay = min(MAX_CRAWL_DELAY, max(REQUEST_DELAY_SECONDS, float(crawl_delay)))

    def allowed(self, url: str) -> bool:
        if self.disallow_all:
            return False
        return self.parser is None or self.parser.can_fetch(USER_AGENT, url)

    def _wait(self) -> None:
        if self._last is not None:
            remaining = self.delay - (time.monotonic() - self._last)
            if remaining > 0:
                time.sleep(remaining)
        self._last = time.monotonic()

    def _fetch(self, url: str) -> Optional[requests.Response]:
        self._wait()
        return _get(url)

    def fetch(self, url: str) -> Optional[requests.Response]:
        return self._fetch(url)


def _page_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()
    # Rivit säilytetään: hinnasto on usein "Palvelu ..... 35 €" omalla rivillään
    lines = (" ".join(line.split()) for line in soup.get_text(separator="\n").splitlines())
    return "\n".join(line for line in lines if line)[:MAX_PAGE_CHARS]


def _html(response: Optional[requests.Response]) -> Optional[BeautifulSoup]:
    if response is None or "text/html" not in response.headers.get("Content-Type", ""):
        return None
    return BeautifulSoup(response.text, "html.parser")


def find_subpages(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """[(luokka, url)] samalta sivustolta, enintään yksi per luokka ja MAX_SUBPAGES yhteensä."""
    host = _site_host(base_url)
    home = base_url.rstrip("/")
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        url = urljoin(base_url, href).split("#", 1)[0]
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or _site_host(url) != host:
            continue
        if url.rstrip("/") == home or parsed.path.lower().endswith(_SKIP_EXTENSIONS):
            continue
        haystack = f"{parsed.path} {a.get_text(' ', strip=True)}".lower()
        for kind, words in SUBPAGE_KEYWORDS.items():
            if kind not in found and url not in found.values() and any(w in haystack for w in words):
                found[kind] = url
                break
        if len(found) >= MAX_SUBPAGES:
            break
    order = list(SUBPAGE_KEYWORDS)
    return sorted(found.items(), key=lambda kv: order.index(kv[0]))


def scan_site(website: str) -> Optional[SiteScan]:
    """Etusivu + enintään 3 alasivua. None jos etusivua ei saa (estetty, ei vastaa, ei tekstiä).

    Rikki-tilan sivu kelpaa jos se silti palauttaa HTML:ää ja tekstiä (esim. HTTP 500 sisällöllä).
    """
    base = _with_scheme(website.strip())
    polite = _Politeness(base)
    blocked: list[str] = []
    if not polite.allowed(base):
        logger.info(f"Sivuston skannaus: robots.txt estää etusivun ({base})")
        return SiteScan(pages=[], blocked=[base])

    home_response = polite.fetch(base)
    soup = _html(home_response)
    if soup is None or home_response is None:
        return None
    final_url = home_response.url or base
    subpages = find_subpages(soup, final_url)
    home_text = _page_text(soup)
    pages: list[SitePage] = []
    if len(home_text) >= MIN_PAGE_CHARS:
        pages.append(SitePage("home", final_url, home_text))

    for kind, url in subpages:
        if not polite.allowed(url):
            blocked.append(url)
            continue
        response = polite.fetch(url)
        sub_soup = _html(response)
        if sub_soup is None or response is None or response.status_code >= 400:
            continue
        text = _page_text(sub_soup)
        if len(text) >= MIN_PAGE_CHARS:
            pages.append(SitePage(kind, response.url or url, text))
    if blocked:
        logger.info(f"Sivuston skannaus: robots.txt estää {len(blocked)} alasivua ({final_url})")
    return SiteScan(pages=pages, blocked=blocked)


# --- AI:n vastauksen tarkistus ---

SITE_FACTS_SYSTEM_PROMPT = """Poimit suomalaisen pienyrityksen verkkosivujen tekstistä rakenteisen datan.

Palauta VAIN yksi JSON-objekti:
{
  "services": [{"name": "palvelun nimi kuten sivulla, 2-60 merkkiä", "price": "hinta täsmälleen kuten sivulla, esim. 35 € tai alk. 45 €, tai null"}],
  "about": "yrityksen oma esittelyteksti sivulta lähes sanatarkasti, max 600 merkkiä, tai null"
}

Säännöt:
- Vain sitä, mikä lukee tekstissä. Älä keksi palveluja, hintoja tai esittelyä.
- Hinta vain jos se lukee samassa kohdassa kuin palvelun nimi. Muuten null.
- Enintään 12 palvelua, tärkeimmät ensin. Ei tuotemerkkejä, aukioloaikoja eikä yhteystietoja.
- Jos tekstissä ei ole palveluja tai esittelyä, palauta tyhjä lista ja null."""


def facts_prompt(scan: SiteScan) -> str:
    parts = []
    for page in scan.pages:
        parts.append(f"=== SIVU ({page.kind}): {page.url}\n{page.text}")
    return "\n\n".join(parts) + "\n\nPalauta JSON."


def _norm(text: str) -> str:
    return " ".join(text.casefold().replace(" ", " ").split())


_NUMBER_RE = re.compile(r"\d+(?:[,.]\d+)?")
_CURRENCY_RE = re.compile(r"€|\beur\w*\b|\b\d+(?:[,.]\d+)?\s*e\b", re.IGNORECASE)
_PRICE_SHAPE_RE = re.compile(r"^[^\d]{0,12}\d[\d\s,.\-–]*\s*(€|e|eur|euroa)?\s*(/[\w ]{1,10})?$", re.IGNORECASE)
PRICE_WINDOW = 160
_WORD_RE = re.compile(r"[\wåäö]{4,}", re.IGNORECASE)
ABOUT_MIN_SOURCE_SHARE = 0.75


def _price_supported(price: str, name: str, pages: list[SitePage]) -> bool:
    """Hinnan luvut ja valuutta löytyvät samalta sivulta enintään PRICE_WINDOW merkin päästä nimestä."""
    numbers = _NUMBER_RE.findall(price)
    if not numbers or not _PRICE_SHAPE_RE.match(price.strip()):
        return False
    target = _norm(name)
    for page in pages:
        text = _norm(page.text)
        start = text.find(target)
        while start != -1:
            window = text[max(0, start - PRICE_WINDOW // 4): start + len(target) + PRICE_WINDOW]
            if _CURRENCY_RE.search(window) and all(
                re.search(rf"(?<![\d,.]){re.escape(n)}(?![\d])", window) for n in numbers
            ):
                return True
            start = text.find(target, start + 1)
    return False


def verify_site_facts(raw: SiteFacts, scan: SiteScan) -> SiteFacts:
    """Pudottaa kaiken, mitä sivujen tekstissä ei ole: nimet, hinnat ja esittelyn."""
    all_text = _norm("\n".join(p.text for p in scan.pages))
    services: list[SiteService] = []
    seen: set[str] = set()
    for service in raw.services:
        key = _norm(service.name)
        if key in seen or key not in all_text:
            continue
        seen.add(key)
        price = service.price.strip() if service.price else None
        if price and not _price_supported(price, service.name, scan.pages):
            logger.info(f"Sivuston hinta hylättiin (ei lähteessä palvelun vieressä): {service.name!r} {price!r}")
            price = None
        services.append(SiteService(name=service.name, price=price))

    about = raw.about.strip() if raw.about else None
    if about:
        words = _WORD_RE.findall(about.casefold())
        share = sum(1 for w in words if w in all_text) / len(words) if words else 0.0
        if share < ABOUT_MIN_SOURCE_SHARE:
            about = None
    return SiteFacts(services=services[:20], about=about, pages=[p.url for p in scan.pages])
