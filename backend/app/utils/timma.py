"""Timma-tuonti: yrityksen julkinen Timma-sivu -> palvelut, osoite, arvosana ja kuvat demoa varten.

Timman yrityssivu (timma.fi/yritys/{slug}) on React-sovellus, joka hakee tietonsa yhdellä julkisella
JSON-pyynnöllä. Haetaan sama JSON, kerran per liidi (välimuisti Lead.timma_data), uudelleen vain Refreshistä.

Suojaukset: vain https://timma.fi/yritys/{slug}, pyyntö aina kiinteään API-osoitteeseen (slug tarkistettu),
ei uudelleenohjauksia, timeout, kokoraja, Content-Type-tarkistus. Arvostelutekstejä, arvostelijoita,
työntekijöitä (nimet, kuvat) tai yrityksen sähköpostia ei poimita.
"""
import json
import logging
import re
from typing import Literal, Optional
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TIMMA_HOST = "timma.fi"
TIMMA_API_URL = "https://timma.fi/api/customers/withservicesandusers/gslug/{slug}/public/v3"
TIMMA_IMAGE_PREFIX = "https://scaled-images.timma.fi/"
USER_AGENT = "AgencyHunter/1.0 (+https://palinweb.fi)"
TIMEOUT = (5, 10)  # yhteys, luku
MAX_BYTES = 512 * 1024
MAX_SERVICES = 40
MAX_IMAGES = 8
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")


class TimmaService(BaseModel):
    category: str = Field(max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=400)
    price_cents: Optional[int] = Field(default=None, ge=0)  # None: hinta piilotettu tai puuttuu
    from_price: bool = False  # "alk."
    duration_min: Optional[int] = Field(default=None, ge=0)


class TimmaData(BaseModel):
    name: str
    street: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    services: list[TimmaService] = Field(default_factory=list, max_length=MAX_SERVICES)
    show_prices: bool = True
    rating_avg: Optional[float] = Field(default=None, ge=0, le=5)
    rating_count: int = Field(default=0, ge=0)
    images: list[str] = Field(default_factory=list, max_length=MAX_IMAGES)
    booking_url: str  # kanoninen https://timma.fi/yritys/{gslug}

    @property
    def address(self) -> Optional[str]:
        if not self.street:
            return None
        place = " ".join(p for p in (self.postal_code, self.city) if p)
        return f"{self.street}, {place}" if place else self.street


class TimmaSnapshot(BaseModel):
    """Tallennetaan Lead.timma_data-sarakkeeseen.

    ok = data käytettävissä, not_found = sivua ei ole, hidden = yritys on piilottanut sivun
    (hideFromMarketplace): dataa ei tallenneta eikä käytetä.
    """
    status: Literal["ok", "not_found", "hidden"]
    slug: str
    data: Optional[TimmaData] = None


class TimmaFetchError(Exception):
    """Verkko-, muoto- tai rajavirhe. Ei tallenneta: seuraava yritys hakee uudelleen."""


def timma_slug(url: Optional[str]) -> Optional[str]:
    """https://timma.fi/yritys/{slug}[/][?…] -> slug. Kaikki muu (http, www, /pro/, alipolut) -> None."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname != TIMMA_HOST or parsed.port is not None:
        return None
    if parsed.username or parsed.password:
        return None
    parts = parsed.path.split("/")
    # "/yritys/slug" -> ["", "yritys", "slug"], "/yritys/slug/" -> [..., ""]
    if len(parts) not in (3, 4) or parts[1] != "yritys" or (len(parts) == 4 and parts[3] != ""):
        return None
    slug = parts[2]
    return slug if SLUG_RE.match(slug) else None


def booking_page_url(slug: str) -> str:
    return f"https://{TIMMA_HOST}/yritys/{slug}"


def _text(value: object, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:limit] if cleaned else None


def _int(value: object) -> Optional[int]:
    # bool on int-alityyppi: ei kelpaa hinnaksi tai kestoksi
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _services(raw: object, show_prices: bool) -> list[TimmaService]:
    if not isinstance(raw, list):
        raise TimmaFetchError("subCategories puuttuu tai ei ole lista")
    out: list[TimmaService] = []
    for category in raw:
        if not isinstance(category, dict) or not isinstance(category.get("services"), list):
            raise TimmaFetchError("kategorian rakenne muuttunut")
        cat_name = _text(category.get("name"), 80) or ""
        for item in category["services"]:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"), 120)
            # forSaleWeb false = ei varattavissa verkossa, ei näy Timman sivulla
            if not name or item.get("forSaleWeb") is False:
                continue
            out.append(TimmaService(
                category=cat_name,
                name=name,
                description=_text(item.get("description"), 400),
                price_cents=_int(item.get("price")) if show_prices else None,
                from_price=bool(item.get("isFromPrice")) and show_prices,
                duration_min=_int(item.get("clientDuration")) or _int(item.get("duration")),
            ))
            if len(out) >= MAX_SERVICES:
                return out
    return out


def _rating(raw: object) -> tuple[Optional[float], int]:
    # [keskiarvo * 10, määrä], esim. [50, 262] = 5,0 / 262 (tarkistettu Timman sivulta: "5 (262)")
    if not isinstance(raw, list) or len(raw) < 2:
        return None, 0
    avg, count = _int(raw[0]), _int(raw[1])
    if not count or avg is None or avg > 50:
        return None, 0
    return round(avg / 10, 1), count


def _images(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    urls: list[str] = []
    for item in raw:
        url = item.get("url") if isinstance(item, dict) else None
        if isinstance(url, str) and url.startswith(TIMMA_IMAGE_PREFIX) and url not in urls:
            urls.append(url)
    return urls[:MAX_IMAGES]


def parse_timma(payload: object, slug: str) -> TimmaSnapshot:
    """Timman JSON -> TimmaSnapshot. Heittää TimmaFetchError jos rakenne on muuttunut."""
    if not isinstance(payload, dict):
        raise TimmaFetchError("vastaus ei ole JSON-objekti")
    # noOnlineBookingIndexing ei estä tuontia: demot ovat noindex-luonnoksia, jotka näytetään vain
    # liikkeelle itselleen, joten hakukoneindeksoinnin kielto ei koske niitä.
    if payload.get("hideFromMarketplace") is True:
        return TimmaSnapshot(status="hidden", slug=slug)
    name = _text(payload.get("name"), 120)
    if not name:
        raise TimmaFetchError("yrityksen nimi puuttuu")
    settings = payload.get("publicSettings")
    show_prices = not (isinstance(settings, dict) and settings.get("showPrices") is False)
    gslug = payload.get("gslug")
    canonical = gslug if isinstance(gslug, str) and SLUG_RE.match(gslug) else slug
    avg, count = _rating(payload.get("rating"))
    data = TimmaData(
        name=name,
        street=_text(payload.get("address"), 120),
        postal_code=_text(payload.get("postalCode"), 10),
        city=_text(payload.get("city"), 60),
        district=_text(payload.get("district"), 60),
        services=_services(payload.get("subCategories"), show_prices),
        show_prices=show_prices,
        rating_avg=avg,
        rating_count=count,
        images=_images(payload.get("images")),
        booking_url=booking_page_url(canonical),
    )
    return TimmaSnapshot(status="ok", slug=slug, data=data)


def fetch_timma(slug: str) -> TimmaSnapshot:
    """Yksi GET Timman julkiseen API:in. Blokkaava: kutsu asyncio.to_thread()-funktiolla."""
    if not SLUG_RE.match(slug):
        raise TimmaFetchError("virheellinen slug")
    try:
        response = requests.get(
            TIMMA_API_URL.format(slug=slug),
            params={"lang": "fi", "country": "FI"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
    except requests.RequestException as e:
        raise TimmaFetchError(f"pyyntö epäonnistui: {e.__class__.__name__}") from e
    try:
        if response.status_code == 404:
            return TimmaSnapshot(status="not_found", slug=slug)
        if response.status_code != 200:
            # 3xx mukaan lukien: uudelleenohjauksia ei seurata
            raise TimmaFetchError(f"HTTP {response.status_code}")
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise TimmaFetchError(f"odottamaton Content-Type {content_type or '-'}")
        body = b""
        for chunk in response.iter_content(chunk_size=16384):
            body += chunk
            if len(body) > MAX_BYTES:
                raise TimmaFetchError("vastaus liian suuri")
    finally:
        response.close()
    try:
        payload = json.loads(body)
    except ValueError as e:
        raise TimmaFetchError("vastaus ei ole JSONia") from e
    # Timman sovellus käsittelee {"status": ...} -vastauksen virheenä (merkitys ei tiedossa): ei tallenneta
    if isinstance(payload, dict) and "status" in payload and "name" not in payload:
        raise TimmaFetchError(f"Timman virhevastaus status={str(payload.get('status'))[:40]}")
    return parse_timma(payload, slug)
