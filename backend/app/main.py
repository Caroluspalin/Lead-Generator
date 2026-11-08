# FILE: backend/app/main.py
import asyncio
import csv
import hashlib
import io
import logging
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from collections import OrderedDict, deque
from typing import AsyncIterator, Callable, Iterable, Iterator, List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from urllib.parse import quote_plus, urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlalchemy import Engine, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from pydantic import BaseModel, Field
import requests

# Tuodaan omat moduulit
from .database import create_db_and_tables, get_session
from .models import (
    Demo, Lead, LeadCreate, LeadUpdate, PlaceStatus, SearchHistoryEntry, EmailDraft, SenderProfile, SenderProfileUpdate,
    utc_now,
)
from .utils import unsplash
from .database import engine
from .demo_publish import (
    ObjectStore,
    PublishError,
    R2Config,
    R2ObjectStore,
    load_r2_config,
    publish_html,
    unpublish,
)
from .demo_site import (
    DemoBusiness,
    DemoImages,
    DemoContent,
    DemoGenerationError,
    DemoSender,
    DemoStoredContent,
    DEMO_SYSTEM_PROMPT,
    PLACE_DETAILS_FIELD_MASK,
    find_repeated_phrases,
    TEMPLATES,
    ScreenshotUnavailable,
    build_demo_prompt,
    demo_asset,
    screenshot_demo,
    fetch_opening_hours,
    is_v2_template,
    price_note_for,
    template_assets,
    new_public_slug,
    new_public_token,
    parse_ai_content,
    render_demo_html,
    retry_prompt,
    template_for_primary_type,
    templates_catalog,
    validate_template_choice,
)
from .utils.scraper import scrape_website_text
from .utils.website_check import SOCIAL_MEDIA_ISSUE, analyze_website, is_social_media_url
from .utils.contact_finder import find_contact_email
from .utils.smtp_client import SmtpConfig, SmtpFailure, build_message, send_mail
from .scoring import lead_score
from .text_quality import FORBIDDEN_PATTERNS, PRICE_RE, find_forbidden_words, word_count  # noqa: F401
from .auth import verify_token, AuthUser

# --- CONFIGURATION ---
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from backend/ so it works whether you run from repo root or backend/
_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env")

# Load API key from environment variable (set in .env file)
# Never commit .env to git - it's in .gitignore
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# SMTP (sähköpostin lähetys)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")

# Safety Limits
MAX_SEARCH_CALLS = 15      # Geocode + Text Search -sivut yhteensä, ehdoton raja per haku
MAX_PAGES_PER_CELL = 3     # Text Search (New): max 20/sivu, max 60 tulosta per kysely
PAGE_SIZE = 20
MAX_RESULTS_PER_QUERY = PAGE_SIZE * MAX_PAGES_PER_CELL  # täysi tulos -> alue voi sisältää enemmän
MAX_SPLIT_DEPTH = 2        # koko alue -> 4 -> 16 ruutua, vain täyttyneet ruudut jaetaan
MAX_WORKERS_WEBSITE = 8   # sivuanalyysi per hakusivu (ilmaisia HTTP-pyyntöjä, ei Places-kutsuja)

# Listahinnat per kutsu (Googlen hinnasto 11/2026, 0-100k-taso, ilman ilmaiskiintiötä).
# Text Search -hinta on Enterprise, koska field maskissa on Enterprise-kenttiä.
PRICE_PER_CALL_USD: Dict[str, float] = {
    "geocode": 5.00 / 1000,
    "text_search": 35.00 / 1000,
}

# URL Config
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Field mask määrää hinnan (korkein SKU laskutetaan koko pyynnöstä): rating, userRatingCount,
# websiteUri ja nationalPhoneNumber ovat Text Search Enterprise -kenttiä. Älä lisää kenttiä
# tarkistamatta hinnoittelua.
PLACES_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.businessStatus",
    "places.primaryType",
    "places.googleMapsUri",
    "nextPageToken",
])

# Load USE_LIVE_GOOGLE from environment (defaults to False)
USE_LIVE_GOOGLE = os.getenv("USE_LIVE_GOOGLE", "False").lower() == "true"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Julkaistujen demojen elinaika ja vanhenemisajon väli
DEMO_TTL_DAYS = int(os.getenv("DEMO_TTL_DAYS", "30"))
DEMO_EXPIRY_INTERVAL_SECONDS = int(os.getenv("DEMO_EXPIRY_INTERVAL_SECONDS", str(6 * 3600)))


async def _demo_expiry_loop() -> None:
    # Ensimmäinen ajo hetken päästä käynnistyksestä, sitten säännöllisesti
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.to_thread(run_demo_expiry)
        except Exception as e:
            logger.error(f"Demojen vanhenemisajo epäonnistui: {e}")
        await asyncio.sleep(DEMO_EXPIRY_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tietokannan alustus käynnistyessä
    create_db_and_tables()
    expiry_task = asyncio.create_task(_demo_expiry_loop()) if get_object_store() else None
    yield
    if expiry_task:
        expiry_task.cancel()


# App Initialization
app = FastAPI(title="Agency Hunter CRM", version="2.1.0", lifespan=lifespan)

# Tuotanto: aseta ALLOWED_ORIGINS=https://app.example.com,https://example.com
# Dev: oletuksena Viten localhost
_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GOOGLE SEARCH LOGIC (Scraper) ---

# Tämä on se vanha "Lead" malli pelkkää hakua varten (ei tallennu kantaan)
class SearchUsage(BaseModel):
    api_calls: int = 0
    geocode_calls: int = 0
    text_search_calls: int = 0
    estimated_cost_usd: float = 0.0


class GoogleSearchResult(BaseModel):
    name: str
    place_id: str
    address: str
    phone: Optional[str] = None
    website: Optional[str] = None
    website_status: str
    website_issue: Optional[str] = None
    discovery_method: str
    rating: Optional[float] = None
    review_count: Optional[int] = None
    business_status: Optional[str] = None
    primary_type: Optional[str] = None
    maps_url: Optional[str] = None
    lead_score: int = 0
    already_saved: bool = False
    # Kunta osoitteesta (naapurialueiden tulokset), muuten haettu kaupunki
    city: Optional[str] = None


class SearchSummary(BaseModel):
    requested: int
    found: int
    # target_reached | call_limit | area_exhausted
    stop_reason: str
    skipped_in_pipeline: int = 0
    skipped_dismissed: int = 0
    skipped_seen: int = 0
    filtered_out: int = 0
    searched_neighbors: bool = False


class SearchResponse(BaseModel):
    results: List[GoogleSearchResult]
    usage: SearchUsage
    summary: Optional[SearchSummary] = None


def normalize_place(place: Dict) -> Dict:
    """Places API (New) -vastauksen place -> sisäinen dict (GoogleSearchResultin kentät)."""
    return {
        "place_id": place.get("id", ""),
        "name": (place.get("displayName") or {}).get("text", ""),
        "address": place.get("formattedAddress", ""),
        "phone": place.get("nationalPhoneNumber"),
        "website": place.get("websiteUri"),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "business_status": place.get("businessStatus"),
        "primary_type": place.get("primaryType"),
        "maps_url": place.get("googleMapsUri"),
    }


def _normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold()
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(text.split())


def _normalize_phone(phone: Optional[str]) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if digits.startswith("00358"):
        digits = "0" + digits[5:]
    elif digits.startswith("358"):
        digits = "0" + digits[3:]
    return digits


def merge_duplicates(places: List[Dict]) -> List[Dict]:
    """Google listaa joskus saman yrityksen kahdella place id:llä.

    Yhdistetään vain kun normalisoitu nimi JA puhelinnumero täsmäävät: pelkkä nimi ei riitä,
    koska ketjuilla on useita toimipisteitä. Säilytetään se, jolla on enemmän arvosteluja.
    """
    kept: Dict[tuple[str, str], Dict] = {}
    passthrough: List[Dict] = []
    for place in places:
        phone = _normalize_phone(place.get("phone"))
        name = _normalize_name(place.get("name") or "")
        if not phone or not name:
            passthrough.append(place)
            continue
        key = (name, phone)
        current = kept.get(key)
        if current is None or (place.get("review_count") or 0) > (current.get("review_count") or 0):
            kept[key] = place
    merged = list(kept.values()) + passthrough
    # Säilytetään alkuperäinen järjestys
    order = {id(p): i for i, p in enumerate(places)}
    return sorted(merged, key=lambda p: order[id(p)])


def drop_permanently_closed(places: List[Dict]) -> List[Dict]:
    # CLOSED_TEMPORARILY jätetään näkyviin (merkitään UI:ssa ja pisteytyksessä)
    return [p for p in places if p.get("business_status") != "CLOSED_PERMANENTLY"]


class GooglePlacesService:
    def __init__(self, api_key: str):
        self.key = api_key
        self._calls: Dict[str, int] = {kind: 0 for kind in PRICE_PER_CALL_USD}
        self._lock = threading.Lock()
        self.searched_neighbors = False

    def _reserve_call(self, kind: str) -> bool:
        """Varaa yhden kutsun budjetista. Lukko pitää rajan myös rinnakkaisissa kutsuissa."""
        with self._lock:
            if sum(self._calls.values()) >= MAX_SEARCH_CALLS:
                logger.warning(f"Search-kutsujen raja ({MAX_SEARCH_CALLS}) saavutettu — ohitetaan kutsu")
                return False
            self._calls[kind] += 1
            return True

    @property
    def calls_used(self) -> int:
        with self._lock:
            return sum(self._calls.values())

    def usage(self) -> SearchUsage:
        with self._lock:
            calls = dict(self._calls)
        cost = sum(PRICE_PER_CALL_USD[kind] * n for kind, n in calls.items())
        return SearchUsage(
            api_calls=sum(calls.values()),
            geocode_calls=calls["geocode"],
            text_search_calls=calls["text_search"],
            estimated_cost_usd=round(cost, 4),
        )

    def _get_json(self, url: str, params: Dict) -> Dict:
        if not self._reserve_call("geocode"):
            return {}
        try:
            r = requests.get(url, params={**params, "key": self.key}, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"API Error ({url}): {e}")
            return {}

    def _post_json(self, url: str, body: Dict) -> Dict:
        if not self._reserve_call("text_search"):
            return {}
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.key,
            "X-Goog-FieldMask": PLACES_FIELD_MASK,
        }
        try:
            r = requests.post(url, json=body, headers=headers, timeout=10)
            if r.status_code >= 400:
                # Places API (New) palauttaa syyn JSON-bodyssa (esim. API ei käytössä projektissa)
                logger.error(f"Places API {r.status_code}: {r.text[:500]}")
                return {}
            return r.json()
        except Exception as e:
            logger.error(f"API Error ({url}): {e}")
            return {}

    # --- Grid-haku ---

    def get_city_bounds(self, city_name: str) -> Optional[Dict]:
        """Hakee kaupungin viewport-rajat Geocoding API:lla (1 search-kutsu)."""
        data = self._get_json(GEOCODE_URL, {"address": f"{city_name}, Finland"})
        if not data.get("results"):
            return None
        return data["results"][0]["geometry"].get("viewport")

    @staticmethod
    def viewport_to_rectangle(viewport: Dict) -> Dict:
        """Geocoding-viewport -> Text Search locationRestriction.rectangle."""
        return {
            "low": {"latitude": viewport["southwest"]["lat"], "longitude": viewport["southwest"]["lng"]},
            "high": {"latitude": viewport["northeast"]["lat"], "longitude": viewport["northeast"]["lng"]},
        }

    @staticmethod
    def split_rectangle(rectangle: Dict) -> List[Dict]:
        """Jakaa suorakaiteen 2x2 neljännekseen ilman aukkoja tai limitystä.

        locationRestriction on tiukka raja, joten vierekkäiset ruudut kattavat koko alueen.
        """
        low, high = rectangle["low"], rectangle["high"]
        mid_lat = (low["latitude"] + high["latitude"]) / 2
        mid_lng = (low["longitude"] + high["longitude"]) / 2
        lats = [(low["latitude"], mid_lat), (mid_lat, high["latitude"])]
        lngs = [(low["longitude"], mid_lng), (mid_lng, high["longitude"])]
        return [
            {"low": {"latitude": la0, "longitude": lo0}, "high": {"latitude": la1, "longitude": lo1}}
            for la0, la1 in lats
            for lo0, lo1 in lngs
        ]

    def iter_cell_pages(self, rectangle: Dict, keyword: str) -> Iterator[List[Dict]]:
        """Text Search (New) yhdelle ruudulle sivu kerrallaan, max MAX_PAGES_PER_CELL sivua.

        Generaattori: jos kuluttaja lopettaa, seuraavaa sivua ei haeta (ei maksua).
        """
        base_body: Dict = {
            "textQuery": keyword,
            "locationRestriction": {"rectangle": rectangle},
            "pageSize": PAGE_SIZE,
            "languageCode": "fi",
            "regionCode": "FI",
        }
        page_token: Optional[str] = None

        for _ in range(MAX_PAGES_PER_CELL):
            if self.calls_used >= MAX_SEARCH_CALLS:
                return
            # Googlen ehto: sivutuspyynnön muiden parametrien pitää olla identtiset
            body = {**base_body, "pageToken": page_token} if page_token else base_body
            data = self._post_json(PLACES_TEXT_SEARCH_URL, body)
            yield data.get("places", [])

            page_token = data.get("nextPageToken")
            if not page_token:
                return

    def search_cell(self, rectangle: Dict, keyword: str) -> List[Dict]:
        return [place for page in self.iter_cell_pages(rectangle, keyword) for place in page]

    @staticmethod
    def neighbor_rectangles(rectangle: Dict) -> List[Dict]:
        """Kahdeksan samankokoista ruutua alueen ympärillä (naapurikunnat ilman lisä-Geocodingia)."""
        low, high = rectangle["low"], rectangle["high"]
        d_lat = high["latitude"] - low["latitude"]
        d_lng = high["longitude"] - low["longitude"]
        return [
            {
                "low": {"latitude": low["latitude"] + i * d_lat, "longitude": low["longitude"] + j * d_lng},
                "high": {"latitude": high["latitude"] + i * d_lat, "longitude": high["longitude"] + j * d_lng},
            }
            for i in (-1, 0, 1)
            for j in (-1, 0, 1)
            if (i, j) != (0, 0)
        ]

    def iter_places(self, city: str, keyword: str, *, expand_neighbors: bool = False) -> Iterator[List[Dict]]:
        """Mukautuva ruudukko sivu kerrallaan, normalisoidut paikat (ei vielä duplikaattien poistoa).

        Text Search palauttaa max 60 tulosta per kysely. Jos alue täyttyy, siellä voi olla
        lisää yrityksiä -> jaetaan 2x2 ja haetaan neljännekset (leveyshaku, max MAX_SPLIT_DEPTH).
        expand_neighbors: kun kaupungin ruudukko on käyty, jatketaan ympäröivillä ruuduilla.
        MAX_SEARCH_CALLS katkaisee haun aina, ja kuluttaja voi lopettaa minkä sivun jälkeen tahansa.
        """
        viewport = self.get_city_bounds(city)
        if not viewport:
            logger.warning(f"Kaupungin '{city}' viewport-rajoja ei löytynyt")
            return

        city_rect = self.viewport_to_rectangle(viewport)
        queue: deque[tuple[Dict, int]] = deque([(city_rect, 0)])
        neighbors_queued = not expand_neighbors
        areas = 0
        while True:
            if not queue:
                if neighbors_queued:
                    return
                neighbors_queued = True
                self.searched_neighbors = True
                logger.info("Kaupungin alue käyty, jatketaan naapurialueille")
                queue.extend((r, 0) for r in self.neighbor_rectangles(city_rect))
            if self.calls_used >= MAX_SEARCH_CALLS:
                logger.warning(f"Kutsuraja täynnä, {len(queue)} aluetta jäi hakematta")
                return
            rect, depth = queue.popleft()
            areas += 1
            found = 0
            for page in self.iter_cell_pages(rect, keyword):
                found += len(page)
                yield [n for n in (normalize_place(p) for p in page) if n["place_id"]]
            saturated = found >= MAX_RESULTS_PER_QUERY
            logger.info(
                f"  Alue {areas} (taso {depth}): {found} tulosta"
                f"{' — täynnä, jaetaan' if saturated and depth < MAX_SPLIT_DEPTH else ''}"
            )
            if saturated and depth < MAX_SPLIT_DEPTH:
                queue.extend((q, depth + 1) for q in self.split_rectangle(rect))

    def search_grid(self, city: str, keyword: str) -> List[Dict]:
        """Koko ruudukko kerralla: uniikit, avoimet ja yhdistetyt paikat."""
        unique: Dict[str, Dict] = {}
        for page in self.iter_places(city, keyword):
            for place in page:
                unique[place["place_id"]] = place

        open_places = drop_permanently_closed(list(unique.values()))
        results = merge_duplicates(open_places)
        usage = self.usage()
        logger.info(
            f"Haku valmis: '{keyword}' / '{city}': {len(results)} yritystä "
            f"({len(unique) - len(open_places)} pysyvästi suljettua pois, "
            f"{len(open_places) - len(results)} duplikaattia yhdistetty), "
            f"{usage.api_calls}/{MAX_SEARCH_CALLS} kutsua "
            f"(geocode {usage.geocode_calls}, text search {usage.text_search_calls}), "
            f"~${usage.estimated_cost_usd:.3f}"
        )
        return results

# --- ENDPOINTS ---

# Mock-hakusana -> Googlen primary_type, jotta demo saa oikean pohjan myös dev-tilassa
_MOCK_PRIMARY_TYPES: list[tuple[tuple[str, ...], str]] = [
    (("parturi", "barber"), "barber_shop"),
    (("kampaamo", "kauneus", "hius", "salon"), "hair_salon"),
    (("kahvila", "cafe", "kahvi"), "cafe"),
    (("ravintola", "lounas", "pizzeria", "restaurant"), "restaurant"),
]


def _mock_primary_type(business_type: str) -> Optional[str]:
    t = business_type.lower()
    return next((ptype for keys, ptype in _MOCK_PRIMARY_TYPES if any(k in t for k in keys)), None)


def _mock_places(business_type: str, city: str) -> List[Dict]:
    """Dev-data: keksityt yritykset (ei oikeita nimiä, numeroita tai sivustoja), vaihtelevat pisteet ja tilat.

    Numerot 040 000 00xx ja .example-verkkotunnukset (RFC 2606) ovat selvästi fiktiivisiä.
    """
    bt = business_type.strip().capitalize()
    low = business_type.strip().lower()
    # (nimi, website, website_status, website_issue, rating, review_count, business_status)
    rows: List[tuple] = [
        (f"{bt} Esimerkki", None, "NO WEBSITE", None, 4.7, 132, "OPERATIONAL"),
        (f"{bt} Malli & Poika", "malli-ja-poika.example", "BROKEN WEBSITE", "HTTP 500", 4.4, 58, "OPERATIONAL"),
        (f"{bt} Kuvitelma", "kuvitelma.example", "INSECURE", "SSL certificate expired", 4.6, 87, "OPERATIONAL"),
        (f"{bt} Fiktio", "fiktio.example", "NOT MOBILE", "no viewport meta", 4.1, 21, "OPERATIONAL"),
        (f"{bt} Express Demo", "express-demo.example", "WEBSITE OK", None, 3.9, 240, "OPERATIONAL"),
        (f"Uusi {low} Testilä", None, "NO WEBSITE", None, None, 0, "OPERATIONAL"),
        (f"{bt} Kulma Esimerkki", None, "NO WEBSITE", None, 4.9, 12, "CLOSED_TEMPORARILY"),
        (f"Vanha {low} Mallila", None, "NO WEBSITE", None, 3.2, 7, "CLOSED_PERMANENTLY"),
        (f"{bt} Premium Esimerkki", "premium-esimerkki.example", "WEBSITE OK", None, 4.8, 410, "OPERATIONAL"),
        (f"{bt} Linna Esimerkki", "linna-esimerkki.example", "UNKNOWN", "HTTP 403", 4.5, 64, "OPERATIONAL"),
    ]
    primary_type = _mock_primary_type(business_type)
    # Tunniste haun mukaan, jotta "vain uudet" -suodatus toimii devissä eri hauille erikseen
    key = hashlib.sha256(f"{low}|{city.strip().lower()}".encode()).hexdigest()[:8]
    return [
        {
            "place_id": f"dev-{key}-{i}",
            "name": name,
            "address": f"Esimerkkikatu {i}, {city}",
            "phone": f"040 000 00{i:02d}" if i % 4 else None,
            "website": website,
            "website_status": status,
            "website_issue": issue,
            "rating": rating,
            "review_count": reviews,
            "business_status": business_status,
            "primary_type": primary_type,
            "maps_url": f"https://www.google.com/maps/search/?api=1&query={quote_plus(f'{name} {city}')}",
        }
        for i, (name, website, status, issue, rating, reviews, business_status) in enumerate(rows, start=1)
    ]


# --- Hakusuodattimet ---

# Lomakkeen sivun tila -> mitä analyze_website-tuloksia se vastaa
SEARCH_STATUS_FILTERS = ("no_website", "broken", "insecure", "not_mobile", "social_only")
# Oikean (ei-some) sivun mahdolliset tilat suodatinta kohden ennen analyysia
_REAL_SITE_STATUSES: Dict[str, tuple[str, ...]] = {
    "broken": ("BROKEN WEBSITE",),
    "insecure": ("INSECURE",),
    "not_mobile": ("NOT MOBILE", "INSECURE"),
}
_ALL_REAL_SITE_STATUSES = ("BROKEN WEBSITE", "INSECURE", "NOT MOBILE", "WEBSITE OK", "UNKNOWN")
DEFAULT_SEARCH_COUNT = 20
MAX_SEARCH_COUNT = 100


class SearchFilters(BaseModel):
    statuses: List[str] = Field(default_factory=list)  # tyhjä = kaikki tilat
    min_score: int = 0
    exclude_closed: bool = False


def status_categories(website_status: Optional[str], website_issue: Optional[str]) -> set[str]:
    issue = website_issue or ""
    if website_status == "NO WEBSITE":
        return {"social_only"} if issue == SOCIAL_MEDIA_ISSUE else {"no_website"}
    if website_status == "BROKEN WEBSITE":
        return {"broken"}
    if website_status == "INSECURE":
        # Salaamaton sivu ilman viewportia on myös "ei mobiili"
        return {"insecure", "not_mobile"} if "no viewport" in issue else {"insecure"}
    if website_status == "NOT MOBILE":
        return {"not_mobile"}
    return set()


def matches_filters(result: GoogleSearchResult, filters: SearchFilters) -> bool:
    if filters.exclude_closed and result.business_status == "CLOSED_TEMPORARILY":
        return False
    if filters.statuses and not (status_categories(result.website_status, result.website_issue) & set(filters.statuses)):
        return False
    return result.lead_score >= filters.min_score


def could_match(place: Dict, filters: SearchFilters) -> bool:
    """Voiko paikka vielä täyttää suodattimet sivuanalyysin jälkeen? Säästää hitaat sivupyynnöt."""
    if filters.exclude_closed and place.get("business_status") == "CLOSED_TEMPORARILY":
        return False
    website = (place.get("website") or "").strip()
    if not website or is_social_media_url(website):
        category = "social_only" if website else "no_website"
        if filters.statuses and category not in filters.statuses:
            return False
        possible: tuple[str, ...] = ("NO WEBSITE",)
    elif filters.statuses:
        possible = tuple(st for f in filters.statuses for st in _REAL_SITE_STATUSES.get(f, ()))
    else:
        possible = _ALL_REAL_SITE_STATUSES
    # Paras mahdollinen pistemäärä sallituilla tiloilla
    return any(
        lead_score(st, place.get("rating"), place.get("review_count"), place.get("business_status")) >= filters.min_score
        for st in possible
    )


_POSTAL_CITY_RE = re.compile(r"\b\d{5}\s+([^,\d]+?)\s*(?:,|$)")


def city_from_address(address: Optional[str]) -> Optional[str]:
    """"Katu 1, 02700 Kauniainen, Suomi" -> "Kauniainen"."""
    match = _POSTAL_CITY_RE.search(address or "")
    return match.group(1).strip() if match else None


class CollectOutcome(BaseModel):
    results: List[GoogleSearchResult]
    target_reached: bool
    skipped: Dict[str, int]
    filtered_out: int


def collect_new_leads(
    pages: Iterable[List[Dict]],
    analyze: Callable[[List[Dict]], List[GoogleSearchResult]],
    *,
    count: int,
    filters: SearchFilters,
    excluded: Dict[str, str],
) -> CollectOutcome:
    """Käy hakusivuja läpi kunnes `count` suodattimet täyttävää uutta liidiä on löytynyt.

    excluded: place_id -> syy (in_pipeline | dismissed | seen). Pois suljetuille ja suodattimiin
    mahtumattomille ei tehdä sivuanalyysia. Lopettaa sivujen kuluttamisen heti kun määrä täyttyy,
    jolloin seuraavia Places-kutsuja ei tehdä.
    """
    seen_ids: set[str] = set()
    found: List[GoogleSearchResult] = []
    skipped = {"in_pipeline": 0, "dismissed": 0, "seen": 0}
    filtered_out = 0
    target_reached = False
    iterator = iter(pages)
    try:
        for page in iterator:
            candidates: List[Dict] = []
            for place in drop_permanently_closed(page):
                pid = place["place_id"]
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
                reason = excluded.get(pid)
                if reason is not None:
                    skipped[reason] = skipped.get(reason, 0) + 1
                elif could_match(place, filters):
                    candidates.append(place)
                else:
                    filtered_out += 1
            for result in analyze(candidates) if candidates else []:
                result.lead_score = lead_score(result.website_status, result.rating, result.review_count, result.business_status)
                if matches_filters(result, filters):
                    found.append(result)
                else:
                    filtered_out += 1
            if len(_merge_results(found)) >= count:
                target_reached = True
                break
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()
    merged = sorted(_merge_results(found), key=lambda r: (-r.lead_score, r.name))
    return CollectOutcome(results=merged[:count], target_reached=target_reached, skipped=skipped, filtered_out=filtered_out)


def _merge_results(results: List[GoogleSearchResult]) -> List[GoogleSearchResult]:
    by_id = {id(r): r for r in results}
    merged = merge_duplicates([{**r.model_dump(), "_key": id(r)} for r in results])
    return [by_id[m["_key"]] for m in merged]


def _finalize_search(
    results: List[GoogleSearchResult],
    business_type: str,
    city: str,
    session: Session,
    user: AuthUser,
    usage: SearchUsage,
    summary: Optional[SearchSummary] = None,
) -> SearchResponse:
    """Pisteyttää, merkitsee jo tallennetut, järjestää (paras ensin), merkitsee näytetyt nähdyiksi
    ja tallentaa hakuhistorian."""
    saved_ids = set(session.exec(
        select(Lead.google_place_id).where(
            Lead.user_id == user.id,
            Lead.google_place_id.in_([r.place_id for r in results]),
        )
    ).all())
    for r in results:
        r.lead_score = lead_score(r.website_status, r.rating, r.review_count, r.business_status)
        r.already_saved = r.place_id in saved_ids
        r.city = city_from_address(r.address) or city
    results.sort(key=lambda r: (-r.lead_score, r.name))

    mark_seen(session, user.id, [r.place_id for r in results])
    session.add(SearchHistoryEntry(user_id=user.id, business_type=business_type, city=city, result_count=len(results)))
    session.commit()
    return SearchResponse(results=results, usage=usage, summary=summary)


def _excluded_places(session: Session, user_id: str, *, only_new: bool) -> Dict[str, str]:
    """place_id -> syy. Pipeline ja hylätyt aina, nähdyt vain "vain uudet" -tilassa."""
    excluded = {
        row.place_id: row.status
        for row in session.exec(select(PlaceStatus).where(PlaceStatus.user_id == user_id)).all()
        if only_new or row.status != "seen"
    }
    # Lead-taulu on pipelinen totuus myös jos tila-rivi puuttuisi
    for pid in session.exec(
        select(Lead.google_place_id).where(Lead.user_id == user_id, Lead.google_place_id.is_not(None))
    ).all():
        if pid:
            excluded[pid] = "in_pipeline"
    return excluded


# 1. HAKU (Google API)
# HUOM: Muutettu polku /leads -> /search, jotta /leads jää tietokannalle
@app.get("/search", response_model=SearchResponse)
async def search_google(
    business_type: str = Query(..., min_length=2),
    city: str = Query(..., min_length=2),
    count: int = Query(DEFAULT_SEARCH_COUNT, ge=1, le=MAX_SEARCH_COUNT),
    status: List[str] = Query(default_factory=list),
    min_score: int = Query(0, ge=0, le=100),
    exclude_closed: bool = Query(False),
    only_new: bool = Query(True),
    expand_neighbors: bool = Query(False),
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    unknown = [s for s in status if s not in SEARCH_STATUS_FILTERS]
    if unknown:
        raise HTTPException(422, f"Unknown status filter: {', '.join(unknown)}")
    filters = SearchFilters(statuses=list(dict.fromkeys(status)), min_score=min_score, exclude_closed=exclude_closed)
    excluded = _excluded_places(session, user.id, only_new=only_new)

    if not USE_LIVE_GOOGLE:
        mock_pages = [_mock_places(business_type, city)]
        outcome = collect_new_leads(
            mock_pages,
            lambda places: [GoogleSearchResult(**p, discovery_method="DEV-MOCK") for p in places],
            count=count, filters=filters, excluded=excluded,
        )
        summary = _search_summary(outcome, count, call_limit_hit=False, searched_neighbors=False)
        return _finalize_search(outcome.results, business_type, city, session, user, SearchUsage(), summary)

    if "AIza" not in GOOGLE_API_KEY:
        raise HTTPException(500, "API Key missing")

    service = GooglePlacesService(GOOGLE_API_KEY)

    def _analyze(places: List[Dict]) -> List[GoogleSearchResult]:
        output = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS_WEBSITE) as ex:
            future_map = {ex.submit(analyze_website, p.get("website")): p for p in places}
            for f in as_completed(future_map):
                check = f.result()
                output.append(GoogleSearchResult(
                    **future_map[f],
                    website_status=check.status,
                    website_issue=check.issue,
                    discovery_method="API",
                ))
        return output

    # Google-kutsut ja website-analyysi blokkaavat -> taustasäikeeseen, event loop ei jäädy
    outcome = await asyncio.to_thread(
        collect_new_leads,
        service.iter_places(city, business_type, expand_neighbors=expand_neighbors),
        _analyze,
        count=count, filters=filters, excluded=excluded,
    )
    summary = _search_summary(
        outcome, count,
        call_limit_hit=service.calls_used >= MAX_SEARCH_CALLS,
        searched_neighbors=service.searched_neighbors,
    )
    usage = service.usage()
    logger.info(
        f"Uudet liidit '{business_type}' / '{city}': {summary.found}/{count} ({summary.stop_reason}), "
        f"{usage.api_calls}/{MAX_SEARCH_CALLS} kutsua, ~${usage.estimated_cost_usd:.3f}"
    )
    return _finalize_search(outcome.results, business_type, city, session, user, usage, summary)


def _search_summary(outcome: CollectOutcome, count: int, *, call_limit_hit: bool, searched_neighbors: bool) -> SearchSummary:
    if outcome.target_reached:
        reason = "target_reached"
    elif call_limit_hit:
        reason = "call_limit"
    else:
        reason = "area_exhausted"
    return SearchSummary(
        requested=count,
        found=len(outcome.results),
        stop_reason=reason,
        skipped_in_pipeline=outcome.skipped.get("in_pipeline", 0),
        skipped_dismissed=outcome.skipped.get("dismissed", 0),
        skipped_seen=outcome.skipped.get("seen", 0),
        filtered_out=outcome.filtered_out,
        searched_neighbors=searched_neighbors,
    )

# 2. TALLENNA LIIDI (Database)
# Sivusto toimii -> kannattaa etsiä sähköpostia (BROKEN/NO WEBSITE/UNKNOWN eivät vastaa luotettavasti)
EMAIL_SEARCH_STATUSES = {"WEBSITE OK", "NOT MOBILE", "INSECURE"}


def can_search_email(lead: Lead) -> bool:
    return bool(lead.website) and lead.website_status in EMAIL_SEARCH_STATUSES


async def _find_email_in_background(lead_id: int, user_id: str, website: str, engine: Engine) -> None:
    """Ajetaan POST /leads -vastauksen jälkeen, ettei tallennus odota sivujen hakua."""
    try:
        found = await asyncio.to_thread(find_contact_email, website)
        if found is None:
            return
        with Session(engine) as session:
            db_lead = session.get(Lead, lead_id)
            # Käyttäjä on voinut poistaa liidin tai asettaa osoitteen käsin välissä
            if db_lead is None or db_lead.user_id != user_id or db_lead.email:
                return
            db_lead.email = found.email
            db_lead.email_source = found.source
            db_lead.updated_at = utc_now()
            session.add(db_lead)
            session.commit()
            logger.info(f"Sähköposti löytyi liidille {lead_id}: {found.email} ({found.source})")
    except Exception as e:
        logger.warning(f"Sähköpostihaku epäonnistui liidille {lead_id}: {e}")


@app.post("/leads", response_model=Lead)
def create_lead(
    lead: LeadCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    # Duplikaattitarkistus käyttäjäkohtaisesti — sama place_id eri käyttäjällä on sallittu
    if lead.google_place_id:
        existing = session.exec(
            select(Lead).where(
                Lead.google_place_id == lead.google_place_id,
                Lead.user_id == user.id,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Lead already exists")

    # Pisteet lasketaan serverissä, ei luoteta clientin arvoon
    score = lead_score(lead.website_status, lead.rating, lead.review_count, lead.business_status)
    db_lead = Lead.model_validate(lead, update={"user_id": user.id, "lead_score": score})
    session.add(db_lead)
    if is_google_place_id(db_lead.google_place_id):
        set_place_status(session, user.id, db_lead.google_place_id, "in_pipeline")
    session.commit()
    session.refresh(db_lead)

    if can_search_email(db_lead) and db_lead.id is not None and db_lead.website:
        background_tasks.add_task(
            _find_email_in_background, db_lead.id, user.id, db_lead.website, session.get_bind()
        )
    return db_lead


@app.post("/leads/{lead_id}/find-email", response_model=Lead)
async def find_lead_email(
    lead_id: int,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    db_lead = session.get(Lead, lead_id)
    if not db_lead or db_lead.user_id != user.id:
        raise HTTPException(404, "Lead not found")
    if not can_search_email(db_lead) or not db_lead.website:
        raise HTTPException(422, "Website is not reachable, cannot search for an email")

    found = await asyncio.to_thread(find_contact_email, db_lead.website)
    if found is not None:
        db_lead.email = found.email
        db_lead.email_source = found.source
        db_lead.updated_at = utc_now()
        session.add(db_lead)
        session.commit()
        session.refresh(db_lead)
    return db_lead

# 3. HAE TALLENNETUT LIIDIT (Database)
@app.get("/leads", response_model=List[Lead])
def read_leads(
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    leads = session.exec(
        select(Lead).where(Lead.user_id == user.id).order_by(Lead.created_at.desc())
    ).all()
    return leads

# 3b. CSV EXPORT
@app.get("/leads/export")
def export_leads_csv(
    ids: str = Query(..., description="Pilkuilla erotetut liidi-ID:t"),
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
) -> StreamingResponse:
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    if not id_list:
        raise HTTPException(400, "No valid IDs provided")

    leads = session.exec(
        select(Lead).where(Lead.id.in_(id_list), Lead.user_id == user.id)
    ).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "Name", "City", "Address", "Phone", "Website", "Website Status", "Stage", "Notes"])
    for lead in leads:
        writer.writerow([
            lead.id,
            lead.name,
            lead.city,
            lead.address or "",
            lead.phone or "",
            lead.website or "",
            lead.website_status or "",
            lead.pipeline_status,
            lead.notes or "",
        ])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
    )

# --- SENDER PROFILE ---

def get_sender_profile(session: Session, user_id: str) -> Optional[SenderProfile]:
    return session.exec(select(SenderProfile).where(SenderProfile.user_id == user_id)).first()


def _clean(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value or None


@app.get("/sender-profile", response_model=SenderProfile)
def read_sender_profile(
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
) -> SenderProfile:
    profile = get_sender_profile(session, user.id)
    if profile is None:
        raise HTTPException(404, "Sender profile not set")
    return profile


@app.put("/sender-profile", response_model=SenderProfile)
def upsert_sender_profile(
    data: SenderProfileUpdate,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
) -> SenderProfile:
    name = data.name.strip()
    intro = data.short_intro.strip()
    if not name or not intro:
        raise HTTPException(422, "name and short_intro are required")

    profile = get_sender_profile(session, user.id) or SenderProfile(user_id=user.id, name=name, short_intro=intro)
    profile.name = name
    profile.short_intro = intro
    profile.company_name = _clean(data.company_name)
    profile.brand_name = _clean(data.brand_name)
    profile.phone = _clean(data.phone)
    profile.website = _clean(data.website)
    profile.updated_at = utc_now()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


# --- SEARCH HISTORY ---

@app.get("/search-history", response_model=List[SearchHistoryEntry])
def get_search_history(
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
) -> list[SearchHistoryEntry]:
    return list(session.exec(
        select(SearchHistoryEntry)
        .where(SearchHistoryEntry.user_id == user.id)
        .order_by(SearchHistoryEntry.searched_at.desc())
        .limit(50)
    ).all())

@app.delete("/search-history/{entry_id}")
def delete_search_history_entry(
    entry_id: int,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    entry = session.get(SearchHistoryEntry, entry_id)
    if not entry or entry.user_id != user.id:
        raise HTTPException(404, "Entry not found")
    session.delete(entry)
    session.commit()
    return {"ok": True}

# --- EMAIL DRAFTS ---

@app.get("/leads/{lead_id}/drafts", response_model=List[EmailDraft])
def get_lead_drafts(
    lead_id: int,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
) -> list[EmailDraft]:
    # Varmista että liidi kuuluu käyttäjälle
    db_lead = session.get(Lead, lead_id)
    if not db_lead or db_lead.user_id != user.id:
        raise HTTPException(404, "Lead not found")

    return list(session.exec(
        select(EmailDraft)
        .where(EmailDraft.lead_id == lead_id, EmailDraft.user_id == user.id)
        .order_by(EmailDraft.created_at.desc())
    ).all())

# 4. PÄIVITÄ LIIDI (Status / Notes)
@app.patch("/leads/{lead_id}", response_model=Lead)
def update_lead(
    lead_id: int,
    lead_update: LeadUpdate,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    db_lead = session.get(Lead, lead_id)
    if not db_lead or db_lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead_data = lead_update.model_dump(exclude_unset=True)
    for key, value in lead_data.items():
        setattr(db_lead, key, value)
    db_lead.updated_at = utc_now()

    session.add(db_lead)
    session.commit()
    session.refresh(db_lead)
    return db_lead

# 5. POISTA LIIDI
@app.delete("/leads/{lead_id}")
def delete_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    db_lead = session.get(Lead, lead_id)
    if not db_lead or db_lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    _remove_lead(session, db_lead)
    # Poistettu liidi ei ole hylätty: se voi tulla hakuun uudelleen, mutta ei "vain uudet" -haussa
    if is_google_place_id(db_lead.google_place_id):
        current = get_place_status(session, user.id, db_lead.google_place_id)
        if current is not None and current.status == "in_pipeline":
            set_place_status(session, user.id, db_lead.google_place_id, "seen")
    session.commit()
    return {"ok": True}


def _remove_lead(session: Session, lead: Lead) -> None:
    """Poistaa liidin ja sen demon (julkaistu demo otetaan ensin pois R2:sta). Ei commitoi."""
    for demo in session.exec(select(Demo).where(Demo.lead_id == lead.id, Demo.user_id == lead.user_id)).all():
        _take_offline(demo)
        session.delete(demo)
    session.delete(lead)


# --- Paikkojen tila (seen / in_pipeline / dismissed) ---

# Googlen place id: kirjaimia, numeroita, _ ja -. dev- = mock-haun tunnisteet (toimivat devissä samoin)
_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,300}$")


def is_google_place_id(place_id: Optional[str]) -> bool:
    # Käsin lisätyillä liideillä on frontendin keksimä manual-tunniste, ei Googlen paikkaa
    return bool(place_id) and not (place_id or "").startswith("manual-") and bool(_PLACE_ID_RE.match(place_id or ""))


def get_place_status(session: Session, user_id: str, place_id: str) -> Optional[PlaceStatus]:
    return session.exec(
        select(PlaceStatus).where(PlaceStatus.user_id == user_id, PlaceStatus.place_id == place_id)
    ).first()


def set_place_status(session: Session, user_id: str, place_id: str, status: str) -> None:
    """Upsert ilman committia."""
    row = get_place_status(session, user_id, place_id)
    if row is None:
        row = PlaceStatus(user_id=user_id, place_id=place_id, status=status)
    else:
        row.status, row.updated_at = status, utc_now()
    session.add(row)


def place_statuses(session: Session, user_id: str, place_ids: List[str]) -> Dict[str, str]:
    if not place_ids:
        return {}
    rows = session.exec(
        select(PlaceStatus).where(PlaceStatus.user_id == user_id, PlaceStatus.place_id.in_(place_ids))
    ).all()
    return {r.place_id: r.status for r in rows}


def mark_seen(session: Session, user_id: str, place_ids: List[str]) -> None:
    """Uusille paikoille seen. Ei koskaan alenna in_pipeline- tai dismissed-tilaa. Ei commitoi."""
    known = place_statuses(session, user_id, place_ids)
    for pid in dict.fromkeys(place_ids):
        if pid not in known and is_google_place_id(pid):
            session.add(PlaceStatus(user_id=user_id, place_id=pid, status="seen"))


def maps_url_for_place(place_id: str) -> str:
    return f"https://www.google.com/maps/place/?q=place_id:{quote_plus(place_id)}"


class DismissedPlace(BaseModel):
    place_id: str
    maps_url: str
    dismissed_at: datetime


class DismissResponse(BaseModel):
    place_id: str
    status: str
    removed_lead_id: Optional[int] = None


def _require_place_id(place_id: str) -> str:
    if not is_google_place_id(place_id):
        raise HTTPException(422, "Invalid place id")
    return place_id


@app.post("/places/{place_id}/dismiss", response_model=DismissResponse)
def dismiss_place(
    place_id: str,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
) -> DismissResponse:
    """Pysyvä hylkäys: paikka ei palaa hakutuloksiin. Jos se on pipelinessa, liidi ja demo poistetaan."""
    _require_place_id(place_id)
    lead = session.exec(select(Lead).where(Lead.user_id == user.id, Lead.google_place_id == place_id)).first()
    removed = lead.id if lead else None
    if lead is not None:
        _remove_lead(session, lead)
    set_place_status(session, user.id, place_id, "dismissed")
    session.commit()
    return DismissResponse(place_id=place_id, status="dismissed", removed_lead_id=removed)


@app.delete("/places/{place_id}/dismiss")
def restore_place(
    place_id: str,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
) -> dict[str, bool]:
    """Palauttaa hylätyn: rivi poistetaan, joten paikka näkyy hauissa taas uutena."""
    _require_place_id(place_id)
    row = get_place_status(session, user.id, place_id)
    if row is None or row.status != "dismissed":
        raise HTTPException(404, "Place is not dismissed")
    session.delete(row)
    session.commit()
    return {"ok": True}


@app.get("/places/dismissed", response_model=List[DismissedPlace])
def list_dismissed_places(
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
) -> List[DismissedPlace]:
    rows = session.exec(
        select(PlaceStatus)
        .where(PlaceStatus.user_id == user.id, PlaceStatus.status == "dismissed")
        .order_by(PlaceStatus.updated_at.desc())
    ).all()
    return [DismissedPlace(place_id=r.place_id, maps_url=maps_url_for_place(r.place_id), dismissed_at=r.updated_at) for r in rows]

# --- AI EMAIL SERVICE ---

# Sähköpostien ja puhelinskriptien malli. gpt-4o-mini poistuu OpenAI:lta 14.1.2027 (deprecations-sivu).
EMAIL_MODEL = os.getenv("EMAIL_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
# Reasoning-malleille (GPT-6-sarja): none | low | medium | high. Tyhjä = ei reasoning-parametria (gpt-4o-mini).
# OpenAI: temperature on sallittu vain kun reasoning effort on "none" tai mallilla ei ole reasoningia.
EMAIL_REASONING_EFFORT = os.getenv("EMAIL_REASONING_EFFORT", "").strip().lower()
# Reasoning-tokenit lasketaan max_completion_tokens-rajaan -> lisävara, ettei vastaus katkea tyhjäksi
REASONING_TOKEN_HEADROOM = 4000
# Demosivujen sisältö: oletuksena sama malli kuin sähköposteissa
SITE_MODEL = os.getenv("SITE_MODEL", "").strip() or EMAIL_MODEL
SITE_REASONING_EFFORT = os.getenv("SITE_REASONING_EFFORT", EMAIL_REASONING_EFFORT).strip().lower()
# Unsplash-kuvat demosivuille. Ilman avainta demo käyttää gradienttia.
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
# Unsplashin attribuutiolinkkien utm_source (sovelluksen nimi Unsplashin developer-portaalissa)
UNSPLASH_APP_NAME = os.getenv("UNSPLASH_APP_NAME", "agency_hunter").strip() or "agency_hunter"
DEMO_LINK_PLACEHOLDER = "[DEMO_LINKKI]"
DEMO_LINK_SENTENCE = "Tein teille jo valmiin luonnoksen, jonka voitte katsoa täältä: {url}"
DEMO_OFFER = DEMO_LINK_SENTENCE.format(url=DEMO_LINK_PLACEHOLDER)

# Lisätään koodissa jokaisen viestin loppuun, jotta ne ovat aina mukana (ei luoteta malliin)
OPT_OUT_LINE = 'Jos tämä ei ole ajankohtaista, vastaa vain "ei kiitos", niin en ota enää yhteyttä.'
SIGN_OFF = "Terveisin,"
MAX_EMAIL_WORDS = 90

# website_issue (tekninen, website_check.py) -> oma, varma havainto te-muodossa.
# Avain täsmätään issue-tekstin alkuun; yhdistetyt syyt ("no HTTPS; no viewport meta") pilkotaan.
ISSUE_DESCRIPTIONS: list[tuple[str, str]] = [
    ("social media only", "löysin teidät vain Facebookista, omaa nettisivua en löytänyt"),
    ("DNS not resolving", "Googlen kautta löytyvä nettisivuosoitteenne ei avaudu"),
    ("connection refused", "nettisivunne ei avautunut, kun yritin avata sen"),
    ("connection failed", "nettisivunne ei avautunut, kun yritin avata sen"),
    ("parked domain", "Googlessa oleva nettisivuosoitteenne johtaa sivulle, jolla ei ole teidän sisältöänne"),
    ("HTTP 404", 'Googlessa oleva linkki sivuillenne johtaa "sivua ei löydy" -ilmoitukseen'),
    ("HTTP 410", 'Googlessa oleva linkki sivuillenne johtaa "sivua ei löydy" -ilmoitukseen'),
    ("HTTP 5", "sivunne näytti virheilmoituksen, kun avasin sen"),
    ("SSL certificate", "kun avasin sivunne, selain varoitti, ettei yhteys ole turvallinen"),
    ("no HTTPS", 'selain merkitsee sivunne "ei turvallinen" -merkinnällä'),
    ("redirects to HTTP", 'selain merkitsee sivunne "ei turvallinen" -merkinnällä'),
    ("no viewport meta", "sivunne ei mukaudu puhelimen näytölle"),
]
STATUS_DESCRIPTIONS: Dict[str, str] = {
    "NO WEBSITE": "en löytänyt teille omaa nettisivua Googlesta",
    "BROKEN WEBSITE": "nettisivunne ei avautunut, kun yritin avata sen",
    "INSECURE": 'selain merkitsee sivunne "ei turvallinen" -merkinnällä',
    "NOT MOBILE": "sivunne ei mukaudu puhelimen näytölle",
}

# Vihje "miksi sillä on väliä" -lauseeseen: arkinen asiakkaan näkökulma, ei pelottelua
WHY_IT_MATTERS: Dict[str, str] = {
    "NO WEBSITE": "moni etsii aukioloajat, hinnat ja yhteystiedot ensin netistä",
    "BROKEN WEBSITE": "Googlesta tulevat asiakkaat päätyvät nyt tyhjään, eivätkä löydä esim. aukioloaikoja",
    "INSECURE": "varoitus saa osan kävijöistä palaamaan hakutuloksiin ennen kuin he näkevät sivunne",
    "NOT MOBILE": "suurin osa etsii palveluja puhelimella",
}

# Pieni, konkreettinen tarjous (ei "keskustella tarkemmin")
OFFERS: Dict[str, str] = {
    "NO WEBSITE": "Voin tehdä teille ilmaisen luonnoksen, jonka näette ennen kuin päätätte mitään.",
    "BROKEN WEBSITE": "Voin katsoa, mistä vika johtuu, ja kertoa mitä korjaus vaatisi.",
    "INSECURE": "Korjaus on yleensä nopea, voin katsoa sen teille.",
    "NOT MOBILE": "Voin näyttää, miltä sivunne näyttäisi puhelimella korjattuna.",
}
DEFAULT_OFFER = "Voin tehdä sivuistanne lyhyen ilmaisen katsauksen ja kertoa, mitä parantaisin."

_SIGN_OFF_RE = re.compile(
    r"^\s*(ystävällisin terveisin|parhain terveisin|terveisin|t\.|kiittäen|kiitos ja mukavaa)\b.*$",
    re.IGNORECASE,
)


def describe_website_problem(website_status: Optional[str], website_issue: Optional[str]) -> Optional[str]:
    """Oma, varma havainto te-muodossa, tai None jos ongelmaa ei saa mainita.

    UNKNOWN ja WEBSITE OK -> None: emme väitä ongelmaa jota ei ole varmistettu.
    """
    if website_status in (None, "UNKNOWN", "WEBSITE OK"):
        return None
    descriptions: list[str] = []
    for part in (website_issue or "").split(";"):
        part = part.strip()
        match = next((text for key, text in ISSUE_DESCRIPTIONS if part.startswith(key)), None)
        if match and match not in descriptions:
            descriptions.append(match)
    if not descriptions:
        return STATUS_DESCRIPTIONS.get(website_status)
    return " ja ".join(descriptions)


def check_generated_text(text: str, *, kind: str, lead_id: int, model: str, max_words: Optional[int] = None) -> list[str]:
    """Lokittaa varoitukset (ei estä): kielletyt sanat, liian pitkä teksti, keksitty hinta."""
    warnings: list[str] = []
    forbidden = find_forbidden_words(text)
    if forbidden:
        warnings.append(f"kielletyt sanat: {', '.join(forbidden)}")
    if max_words is not None and word_count(text) > max_words + 20:
        warnings.append(f"liian pitkä: {word_count(text)} sanaa (tavoite ~{max_words})")
    if PRICE_RE.search(text):
        warnings.append("tekstissä mainitaan hinta")
    for w in warnings:
        logger.warning(f"Generoitu {kind} (liidi {lead_id}, {model}): {w}")
    return warnings


def email_subject(lead: Lead) -> str:
    issue = lead.website_issue or ""
    if lead.website_status == "NO WEBSITE":
        return "Löysin teidät Facebookista" if issue.startswith("social media only") else "Kysymys nettisivuista"
    if lead.website_status == "BROKEN WEBSITE" and issue.startswith(("DNS", "connection")):
        return "Nettisivunne ei aukea"
    if lead.website_status in ("BROKEN WEBSITE", "INSECURE"):
        return "Huomasin jotain sivuistanne"
    if lead.website_status == "NOT MOBILE":
        return "Sivunne puhelimella"
    return "Kysymys nettisivuistanne"


_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_MD_BULLET_RE = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)


def strip_markdown(text: str) -> str:
    """Pelkkä teksti modaaliin ja kopiointiin: poistaa otsikot, lihavoinnit ja luettelomerkit, tiivistää tyhjät rivit."""
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_BOLD_RE.sub(r"\2", text)
    text = _MD_BULLET_RE.sub("", text)
    # "1. Avaus\n\nHei..." (otsikko omalla rivillä) -> "1. Avaus: Hei..."
    text = re.sub(r"^(\d\.\s[^\n:]{1,40}?):?\s*\n+(?=\S)", r"\1: ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{2,}(?=\d\.\s)", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def display_website(url: Optional[str]) -> Optional[str]:
    """Allekirjoitukseen ilman https:// ja loppukauttaviivaa (palinweb.fi)."""
    if not url:
        return None
    shown = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE).rstrip("/")
    return shown or None


def build_signature(profile: SenderProfile) -> str:
    """Nimi / brändi · sivusto / puhelin. Puuttuvat osat jätetään pois (ei tyhjiä rivejä tai irtopisteitä).

    Ilman brand_namea käytetään company_namea, jotta vanhojen profiilien allekirjoitus ei kutistu.
    """
    brand = profile.brand_name or profile.company_name
    middle = " · ".join(part for part in (brand, display_website(profile.website)) if part)
    return "\n".join(line for line in (profile.name, middle, profile.phone) if line)


def strip_model_sign_off(text: str) -> str:
    """Poistaa mallin mahdollisesti kirjoittaman lopputervehdyksen/allekirjoituksen (koodi lisää oman)."""
    lines = text.rstrip().splitlines()
    for i in range(len(lines) - 1, max(-1, len(lines) - 6), -1):
        if _SIGN_OFF_RE.match(lines[i]) or "[nimesi]" in lines[i].lower():
            lines = lines[:i]
    return "\n".join(lines).rstrip()


_LINK_PLACEHOLDER_RE = re.compile(r"\[[^\]\n]{0,30}linkki[^\]\n]{0,30}\]", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")


# Lause, joka mainitsee luonnoksen (esim. NO WEBSITE -tarjous "Voin tehdä teille ilmaisen luonnoksen...")
_DRAFT_SENTENCE_RE = re.compile(r"[^.!?\n]*\bluonno(s|ksen|ksia|kse\w*)\b[^.!?\n]*[.!?:]?[^\S\n]*(\S*\[[^\]\n]*linkki[^\]\n]*\])?", re.IGNORECASE)
_SHORT_CLOSING_MAX = 60


def place_demo_link(text: str, demo_url: str) -> str:
    """Lisää demolinkin tarjouskohtaan ilman toistoa: luonnosta koskeva lause korvataan linkkilauseella,
    muuten linkkilause omaksi kappaleekseen ennen lyhyttä loppukysymystä (esim. "Kiinnostaisiko?")."""
    if demo_url in text:
        return text
    sentence = DEMO_LINK_SENTENCE.format(url=demo_url)
    match = _DRAFT_SENTENCE_RE.search(text)
    if match:
        lead_ws = len(match.group(0)) - len(match.group(0).lstrip())
        return text[: match.start() + lead_ws] + sentence + text[match.end():]
    paragraphs = text.rstrip().split("\n\n")
    if len(paragraphs) >= 2 and len(paragraphs[-1]) <= _SHORT_CLOSING_MAX:
        return "\n\n".join(paragraphs[:-1] + [sentence, paragraphs[-1]])
    return f"{text.rstrip()}\n\n{sentence}"


def insert_demo_link(text: str, demo_url: Optional[str]) -> str:
    """Demolinkki lisätään aina koodissa: paikkamerkki korvataan, mallin keksimät osoitteet poistetaan."""
    text = _URL_RE.sub("", text)
    if demo_url is None:
        # Ilman julkaistua demoa ei linkkiä eikä linkkiin viittaavaa lausetta
        text = re.sub(r"[^.!?\n]*\[[^\]\n]*linkki[^\]\n]*\][.!?]?[^\S\n]*", "", text, flags=re.IGNORECASE)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    if _LINK_PLACEHOLDER_RE.search(text):
        text = _LINK_PLACEHOLDER_RE.sub(demo_url, text, count=1)
        return _LINK_PLACEHOLDER_RE.sub("", text)
    return place_demo_link(text, demo_url)


def add_demo_link_to_body(body: str, demo_url: str) -> str:
    """Valmiiseen luonnokseen (allekirjoitus + opt-out mukana) linkki ilman uutta AI-kutsua."""
    if demo_url in body:
        return body
    marker = f"\n\n{SIGN_OFF}\n"
    head, sep, tail = body.partition(marker)
    if not sep:
        return place_demo_link(body, demo_url)
    return f"{place_demo_link(head, demo_url)}{sep}{tail}"


def finalize_email_body(text: str, profile: SenderProfile, demo_url: Optional[str] = None) -> str:
    body = insert_demo_link(strip_model_sign_off(text), demo_url)
    return f"{body}\n\n{SIGN_OFF}\n{build_signature(profile)}\n\n{OPT_OUT_LINE}"


# --- Sähköposti julkaistun demon kanssa ---
# Malli kirjoittaa vain kappaleet 1–2 (kuka olen + miten löysin, mitä asiakkaille tapahtuu nyt).
# Kappaleet 3–5 ja allekirjoitus tulevat koodista, joten linkki, riskittömyys ja seuraava askel
# ovat aina mukana, eikä viesti pääty mielipidekysymykseen ("Mitä pidätte?").

DEMO_EMAIL_MAX_WORDS = 110  # koko viesti ennen allekirjoitusta
DEMO_MODEL_MAX_WORDS = 55  # mallin kappaleet 1–2; koodin osuus on n. 50 sanaa

DEMO_LINK_PARAGRAPH = "Tein teille luonnoksen siitä, miltä sivunne voisivat näyttää:\n{url}\nVoitte katsoa sen suoraan puhelimella."
DEMO_RISK_PARAGRAPH = (
    "Luonnos on ilmainen eikä sido teitä mihinkään. Jos se näyttää hyvältä, "
    "viimeistelen sen teidän omilla tiedoillanne ja kuvillanne."
)
DEMO_NEXT_STEP_WITH_PHONE = "Jos haluatte jatkaa, voitte vastata suoraan tähän viestiin tai soittaa minulle numeroon {phone}."
DEMO_NEXT_STEP = "Jos haluatte jatkaa, voitte vastata suoraan tähän viestiin."

# Mitä asiakkaalle konkreettisesti tapahtuu nyt (vihje kappaleeseen 2). Tarkin osuma issue-tekstistä ensin.
CUSTOMER_IMPACT_BY_ISSUE: list[tuple[str, str]] = [
    ("social media only", "Googlesta asiakas löytää teidät vain Facebookin kautta, eikä sieltä näe palveluitanne, hintoja tai aukioloaikoja yhdellä silmäyksellä."),
    ("DNS not resolving", 'Kun asiakas painaa Googlessa "Verkkosivusto"-linkkiä, sivu ei aukea lainkaan.'),
    ("connection", 'Kun asiakas painaa Googlessa "Verkkosivusto"-linkkiä, sivu ei aukea lainkaan.'),
    ("parked domain", 'Kun asiakas painaa Googlessa "Verkkosivusto"-linkkiä, hän päätyy sivulle, jolla ei ole teidän tietojanne.'),
    ("HTTP 404", 'Kun asiakas painaa Googlessa "Verkkosivusto"-linkkiä, hän näkee "sivua ei löydy" -ilmoituksen.'),
    ("HTTP 410", 'Kun asiakas painaa Googlessa "Verkkosivusto"-linkkiä, hän näkee "sivua ei löydy" -ilmoituksen.'),
    ("HTTP 5", 'Kun asiakas painaa Googlessa "Verkkosivusto"-linkkiä, hän näkee virheilmoituksen palveluiden ja aukioloaikojen sijaan.'),
    ("SSL certificate", "Kun asiakas avaa sivunne, selain näyttää ensin varoituksen, ettei yhteys ole turvallinen, ja moni palaa siitä takaisin hakutuloksiin."),
    ("no HTTPS", 'Selain merkitsee sivunne osoiteriville "ei turvallinen", mikä saa osan kävijöistä epäröimään.'),
    ("redirects to HTTP", 'Selain merkitsee sivunne osoiteriville "ei turvallinen", mikä saa osan kävijöistä epäröimään.'),
    ("no viewport meta", "Puhelimella sivunne näkyy pienenä tietokoneversiona, jota pitää suurentaa sormilla."),
]
CUSTOMER_IMPACT_BY_STATUS: Dict[str, str] = {
    "NO WEBSITE": "Asiakas löytää teidät Google-kartalta, mutta ei näe palveluitanne, hintoja eikä aukioloaikoja, vaan joutuu soittamaan tai etsimään tiedot muualta.",
    "BROKEN WEBSITE": 'Kun asiakas painaa Googlessa "Verkkosivusto"-linkkiä, sivu ei aukea.',
    "INSECURE": "Kun asiakas avaa sivunne, selain varoittaa, ettei yhteys ole turvallinen.",
    "NOT MOBILE": "Puhelimella sivunne näkyy pienenä tietokoneversiona, jota pitää suurentaa sormilla.",
}
# UNKNOWN / WEBSITE OK: ei väitetä ongelmaa, kerrotaan mitä luonnos tekee helpommaksi
CUSTOMER_IMPACT_DEFAULT = "Uudella sivulla palvelut, aukioloajat ja yhteystiedot löytyvät puhelimellakin yhdellä silmäyksellä."

_GREETING_LINE_RE = re.compile(r"^\s*(hei|moi|hyvä vastaanottaja|hei teille|tervehdys)\b[^\n]{0,40}[,!.]?\s*$", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+[\"”)]*|[^.!?]+$")
_DRAFT_MENTION_RE = re.compile(r"\bluonno(s|ks)", re.IGNORECASE)


def customer_impact(website_status: Optional[str], website_issue: Optional[str]) -> str:
    if website_status in (None, "UNKNOWN", "WEBSITE OK"):
        return CUSTOMER_IMPACT_DEFAULT
    first_issue = (website_issue or "").split(";")[0].strip()
    match = next((text for key, text in CUSTOMER_IMPACT_BY_ISSUE if first_issue.startswith(key)), None)
    return match or CUSTOMER_IMPACT_BY_STATUS.get(website_status, CUSTOMER_IMPACT_DEFAULT)


def demo_email_subject(lead: Lead) -> str:
    # Ei yritysmäinen; "uusista" kun yrityksellä on jo jonkinlainen sivu
    if lead.website_status == "NO WEBSITE":
        return "Tein teille luonnoksen nettisivuista"
    return "Tein teille luonnoksen uusista nettisivuista"


def _drop_sentences(paragraph: str, predicate: Callable[[str], bool]) -> str:
    kept = [s for s in _SENTENCE_RE.findall(paragraph) if s.strip() and not predicate(s)]
    return " ".join(s.strip() for s in kept)


def clean_demo_paragraphs(text: str) -> list[str]:
    """Mallin kappaleet 1–2 siistittynä: ei tervehdystä, linkkejä, luonnosmainintaa eikä kysymyksiä.

    Koodi kirjoittaa linkin, tarjouksen ja seuraavan askeleen, joten mallin vastaavat lauseet
    poistetaan toiston ja loppukysymysten ("Mitä pidätte...?") estämiseksi. Yli 2 kappaletta -> 2 ensimmäistä.
    """
    text = _URL_RE.sub("", _LINK_PLACEHOLDER_RE.sub("", strip_model_sign_off(text)))
    paragraphs: list[str] = []
    # Kappaleet ensin: strip_markdown nielee #-otsikkoa edeltävän tyhjän rivin
    for raw in re.split(r"\n\s*\n", text):
        lines = [ln for ln in strip_markdown(raw).splitlines() if ln.strip() and not _GREETING_LINE_RE.match(ln)]
        paragraph = " ".join(ln.strip() for ln in lines)
        paragraph = _drop_sentences(
            paragraph,
            lambda s: s.rstrip().rstrip('"”)').endswith("?") or bool(_DRAFT_MENTION_RE.search(s)),
        )
        paragraph = re.sub(r"\s{2,}", " ", paragraph).strip()
        if paragraph:
            paragraphs.append(paragraph)
    return paragraphs[:2]


def demo_next_step(profile: SenderProfile) -> str:
    return DEMO_NEXT_STEP_WITH_PHONE.format(phone=profile.phone) if profile.phone else DEMO_NEXT_STEP


def build_demo_email_body(text: str, profile: SenderProfile, demo_url: str) -> str:
    """Hei + mallin kappaleet 1–2 + linkki omalla rivillään + riskittömyys + seuraava askel + allekirjoitus."""
    parts = ["Hei,", *clean_demo_paragraphs(text), DEMO_LINK_PARAGRAPH.format(url=demo_url), DEMO_RISK_PARAGRAPH, demo_next_step(profile)]
    head = "\n\n".join(parts)
    return f"{head}\n\n{SIGN_OFF}\n{build_signature(profile)}\n\n{OPT_OUT_LINE}"


def email_head(body: str) -> str:
    """Viesti ennen allekirjoitusta (sanamäärän tarkistukseen)."""
    return body.split(f"\n\n{SIGN_OFF}\n", 1)[0]


# --- Demojen julkaisu (R2 + Worker) ---

_object_store_cache: dict[R2Config, R2ObjectStore] = {}


def get_r2_config() -> Optional[R2Config]:
    return load_r2_config()


def get_object_store() -> Optional[ObjectStore]:
    """None jos R2-asetukset puuttuvat. Testit korvaavat tämän fake-storella."""
    config = get_r2_config()
    if config is None:
        return None
    if config not in _object_store_cache:
        _object_store_cache[config] = R2ObjectStore(config)
    return _object_store_cache[config]


def demo_path(demo: Demo) -> str:
    """Julkisen osoitteen polku ja R2-avaimen nimi: slug, tai token ennen slugeja luoduilla demoilla."""
    return demo.public_slug or demo.public_token


def _demo_path_taken(session: Session, path: str) -> bool:
    # Slugit ja tokenit jakavat saman polkunimiavaruuden (/demo/{polku}, Worker /{polku})
    return session.exec(
        select(Demo.id).where(or_(Demo.public_slug == path, Demo.public_token == path))
    ).first() is not None


def demo_public_url(demo: Demo) -> Optional[str]:
    """Julkinen linkki vain julkaistulle demolle: {DEMO_PUBLIC_BASE_URL}/{slug tai token}."""
    config = get_r2_config()
    if demo.status != "published" or config is None:
        return None
    return config.public_url(demo_path(demo))


def _is_expired(demo: Demo) -> bool:
    return demo.status == "expired" or bool(demo.expires_at and _as_utc(demo.expires_at) <= utc_now())


def get_published_demo(session: Session, lead: Lead) -> Optional[Demo]:
    """Sähköpostiin kelpaa vain julkaistu ja voimassa oleva demo (luonnoksen linkki ei toimi vastaanottajalla)."""
    demo = session.exec(select(Demo).where(Demo.lead_id == lead.id, Demo.user_id == lead.user_id)).first()
    if demo is None or demo.status != "published" or _is_expired(demo) or demo_public_url(demo) is None:
        return None
    return demo


def _take_offline(demo: Demo) -> bool:
    """Poistaa julkaistun demon R2:sta. Virheessä Worker palauttaa silti 410 vanhenemisen jälkeen."""
    if demo.status != "published":
        return True
    store = get_object_store()
    return unpublish(store, demo_path(demo)) if store else False


def _republish_if_published(demo: Demo) -> None:
    """Muokkauksen jälkeen julkaistu versio päivitetään samaan osoitteeseen. Virhe -> 502 ennen committia."""
    if demo.status != "published":
        return
    store = get_object_store()
    if store is None:
        raise HTTPException(503, "Publishing not configured (R2_* and DEMO_PUBLIC_BASE_URL in backend .env)")
    try:
        publish_html(store, demo_path(demo), demo.html, demo.expires_at, template_assets(demo.template))
    except PublishError as e:
        raise HTTPException(502, str(e))


def run_demo_expiry(now: Optional[datetime] = None, bind: Optional[Engine] = None) -> dict[str, int]:
    """Vanhentuneet julkaisut: Hired-liidin demo jatketaan, muut poistetaan R2:sta ja merkitään expired."""
    now = now or utc_now()
    store = get_object_store()
    counts = {"expired": 0, "extended": 0, "failed": 0}
    if store is None:
        return counts
    with Session(bind or engine) as session:
        due = [
            d for d in session.exec(select(Demo).where(Demo.status == "published")).all()
            if d.expires_at and _as_utc(d.expires_at) <= now
        ]
        for demo in due:
            lead = session.get(Lead, demo.lead_id)
            if lead is not None and lead.pipeline_status == "Hired":
                demo.expires_at = now + timedelta(days=DEMO_TTL_DAYS)
                try:
                    publish_html(store, demo_path(demo), demo.html, demo.expires_at, template_assets(demo.template))
                    counts["extended"] += 1
                except PublishError as e:
                    logger.error(f"Demon jatko epäonnistui (liidi {demo.lead_id}): {e}")
                    counts["failed"] += 1
                    continue
            else:
                if not unpublish(store, demo_path(demo)):
                    counts["failed"] += 1
                demo.status = "expired"
                counts["expired"] += 1
            session.add(demo)
        session.commit()
    if any(counts.values()):
        logger.info(f"Demojen vanhenemisajo: {counts}")
    return counts


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


EMAIL_SYSTEM_PROMPT = f"""Kirjoitat suomeksi lyhyen ensimmäisen yhteydenoton sähköpostin paikalliselle yritykselle.
Lähettäjä on yksityinen tekijä (tiedot LÄHETTÄJÄ-kohdassa). Viestin pitää kuulostaa oikealta ihmiseltä, joka on
oikeasti katsonut yrityksen tiedot — ei markkinointiviestiltä.

PAKOLLISET SÄÄNNÖT:
1. Te-muoto johdonmukaisesti koko viestissä (teidän, teille, sivunne, voitte). Ei koskaan sinä-muotoa.
2. Aloita "Hei," ja heti ensimmäinen lause kertoo kuka olen ja miten löysin yrityksen,
   esim. "Olen Palin ja teen nettisivuja paikallisille yrityksille. Etsin parturi-kampaamoja Kauniaisista ja huomasin, että..."
   Käytä LÄHETTÄJÄ-kohdan nimeä ja esittelyä, toimialaa ja kaupunkia (taivuta luontevasti).
   Älä käytä yrityksen pitkää virallista nimeä (esim. "Parturi-Kampaamo Taina Lantiainen").
   Käytä luontevaa lyhyttä muotoa (esim. "Tainan kampaamo"), "teidän kampaamonne/ravintolanne" tai jätä nimi pois.
3. HAVAINTO kerrotaan omana, varmana havaintona konkreettisesti (esim. "Kun avasin sivunne, selain varoitti...",
   "Googlen kautta löytyvä osoitteenne ei avaudu", "Löysin teidät vain Facebookista").
   Älä arvaile ("saattaa", "voi olla") kun havainto on annettu.
   Jos havaintoa ei ole annettu, älä keksi ongelmaa.
4. Yksi lause siitä, miksi sillä on väliä heidän asiakkailleen (käytä vihjettä). Ei pelottelua, ei liioittelua.
5. Tarjous: käytä TARJOUS-kohdan lausetta (voit muotoilla hieman). Pieni ja konkreettinen.
   Älä ehdota "keskustelua tarkemmin" tai palaveria.
   Jos TARJOUS sisältää [DEMO_LINKKI], kirjoita se täsmälleen sellaisenaan (hakasulkeineen) lauseen loppuun.
   Älä koskaan kirjoita itse mitään verkko-osoitetta.
6. Lopeta yhteen kevyeen kysymykseen tai toteamukseen (esim. "Kiinnostaisiko?").
7. Jäänmurtaja VERKKOSIVUN SISÄLLÖSTÄ vain, jos sieltä löytyy jotain konkreettista ja erityistä
   (esim. tietty palvelu, merkki, historia). Muuten EI jäänmurtajaa ollenkaan. Älä kehu yritystä yleisesti.
8. Pituus: enintään noin {MAX_EMAIL_WORDS} sanaa. Lyhyet kappaleet.
9. KIELLETYT sanat ja fraasit: ihana, upea, mahtava, ainutlaatuinen, intohimo, ratkaisu, kokonaisvaltainen,
   digitaalinen läsnäolo, nostaa seuraavalle tasolle, innovatiivinen, räätälöity, huippu-, saumaton, synergia,
   liiketoiminnan kasvu, keskustella tarkemmin. Ei teknistä jargonia (SSL, HTTPS, DNS, sertifikaatti, domain, viewport, virhekoodit).
10. Älä lupaa hintoja tai aikatauluja.
11. ÄLÄ kirjoita lopputervehdystä, allekirjoitusta tai "jos ei kiinnosta" -riviä — ne lisätään automaattisesti.
12. Palauta VAIN viestin teksti (ei subject-riviä)."""

DEMO_EMAIL_SYSTEM_PROMPT = f"""Kirjoitat suomeksi KAKSI lyhyttä kappaletta ensimmäisen yhteydenoton sähköpostiin paikalliselle
yritykselle. Lähettäjä on yksityinen tekijä (tiedot LÄHETTÄJÄ-kohdassa), joka on jo tehnyt yritykselle luonnoksen
nettisivuista. Viestin muut osat (tervehdys, linkki luonnokseen, tarjous, yhteydenottopyyntö, allekirjoitus)
lisätään automaattisesti — älä kirjoita niitä.

KAPPALE 1: kuka olen ja miten löysin yrityksen. Yksi tai kaksi lausetta, esim.
   "Olen Palin ja teen nettisivuja paikallisille yrityksille. Etsin parturi-kampaamoja Kauniaisista ja löysin teidät Googlesta."
   Käytä LÄHETTÄJÄ-kohdan nimeä ja esittelyä, toimialaa ja kaupunkia (taivuta luontevasti).
KAPPALE 2: mitä asiakkaille tapahtuu nyt, konkreettisesti ASIAKKAAN TILANNE -kohdan mukaan. Yksi tai kaksi lausetta.
   Kerro se omana havaintona asiakkaan näkökulmasta, ei yleistä "moni etsii netistä" -lausetta.
   Ei pelottelua, ei liioittelua, ei lupauksia.

SÄÄNNÖT:
- Te-muoto johdonmukaisesti (teidän, teille, sivunne, voitte). Ei koskaan sinä-muotoa.
- Älä käytä yrityksen pitkää virallista nimeä (esim. "Parturi-Kampaamo Taina Lantiainen"). Käytä luontevaa
  lyhyttä muotoa (esim. "Tainan kampaamo"), "teidän kampaamonne/ravintolanne" tai jätä nimi pois.
- EI kysymyksiä lainkaan. EI mielipidekysymyksiä ("Mitä pidätte...?", "Mitä mieltä olette...?", "Kiinnostaisiko?").
- Älä mainitse luonnosta, linkkiä, hintaa tai tarjousta. Älä kirjoita verkko-osoitteita.
- Ei tervehdystä ("Hei"), ei lopputervehdystä, ei allekirjoitusta.
- Yhteensä enintään noin {DEMO_MODEL_MAX_WORDS} sanaa. Erota kappaleet tyhjällä rivillä.
- KIELLETYT sanat ja fraasit: ihana, upea, mahtava, ainutlaatuinen, intohimo, ratkaisu, kokonaisvaltainen,
  digitaalinen läsnäolo, nostaa seuraavalle tasolle, innovatiivinen, räätälöity, huippu-, saumaton, synergia,
  liiketoiminnan kasvu, keskustella tarkemmin, saattaa. Ei teknistä jargonia (SSL, HTTPS, DNS, sertifikaatti,
  domain, viewport, virhekoodit).
- Palauta VAIN nämä kaksi kappaletta."""

CALL_SCRIPT_SYSTEM_PROMPT = """Kirjoitat suomeksi lyhyen (n. 30 sekuntia puhuttuna) puhelinrungon soittajalle, joka soittaa
paikalliselle yritykselle ensimmäistä kertaa. Kuulostaa tavalliselta ihmiseltä, ei myyntikoulutukselta.

RAKENNE (käytä täsmälleen näitä otsikoita):
1. Avaus: "Hei, [nimi] täällä" + yksi lause kuka olen (LÄHETTÄJÄ-kohdasta) + "Onko teillä hetki, vai soitanko myöhemmin?"
2. Havainto: yksi arkikielinen lause HAVAINTO-kohdasta omana havaintona, yhtä konkreettisesti kuin sähköpostissa.
   Jos havaintoa ei ole annettu, älä keksi ongelmaa — sano lyhyesti miksi soitat.
3. Tarjous: TARJOUS-kohdan lause puhekielisesti + yksi suora kysymys (esim. "Kiinnostaisiko?").
   EI konsulttimaisia kysymyksiä ("miten olette huolehtineet...", "mitkä ovat tavoitteenne...").
4. Jos "ei kiinnosta": käytä täsmälleen: "Selvä, kiitos ajastanne, mukavaa päivää!"
5. Jos kysyvät hintaa: yksi tai kaksi lausetta: hinta riippuu siitä mitä tarvitsette, ja ehdota ilmaista luonnosta
   tai lyhyttä tapaamista. ÄLÄ mainitse mitään euromääriä.

SÄÄNNÖT:
- Te-muoto johdonmukaisesti. Lyhyitä lauseita, luonteva puhekieli.
- Käytä LÄHETTÄJÄ-kohdan oikeaa nimeä (ei paikkamerkkejä).
- Älä käytä yrityksen pitkää virallista nimeä (esim. "Parturi-Kampaamo Taina Lantiainen").
  Käytä luontevaa lyhyttä muotoa (esim. "Tainan kampaamo"), "teidän kampaamonne/ravintolanne" tai jätä nimi pois.
- Pelkkä teksti: EI markdown-muotoilua (ei #-otsikoita, ei **lihavointia**, ei luettelomerkkejä).
  Jokainen kohta omalla rivillään muodossa "1. Avaus: ...".
- Ei teknistä jargonia, ei liioittelua, ei pelottelua, ei kiellettyjä sanoja
  (ihana, upea, mahtava, ainutlaatuinen, intohimo, ratkaisu, kokonaisvaltainen, digitaalinen läsnäolo, seuraavalle tasolle).
- Palauta vain runko otsikoineen."""


class EmailGenerateRequest(BaseModel):
    instruction: Optional[str] = None
    # "Julkaise ja tee sähköposti" -ketju: ilman julkaistua demoa 409, ei hiljaa linkitöntä luonnosta
    require_demo_link: bool = False


class DemoLinkRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class DemoLinkResponse(BaseModel):
    body: str
    demo_url: str


class EmailGenerateResponse(BaseModel):
    subject: str
    body: str
    model: str


class CallScriptResponse(BaseModel):
    script: str
    model: str


def _prompt_facts(lead: Lead, profile: SenderProfile, *, has_demo: bool = False) -> list[str]:
    parts = [
        "LÄHETTÄJÄ (minä):",
        f"- Nimi: {profile.name}",
        f"- Yritys: {profile.company_name or '(ei yritysnimeä, esiinny omalla nimellä)'}",
        f"- Esittely: {profile.short_intro}",
        "",
        "VASTAANOTTAJA:",
        f"- Yritys: {lead.name}",
        f"- Kaupunki: {lead.city}",
    ]
    if lead.primary_type:
        parts.append(f"- Toimiala (Googlen luokka englanniksi, käännä luontevasti suomeksi): {lead.primary_type}")
    if lead.review_count:
        parts.append(f"- Google-arvostelut: {lead.rating} / 5 ({lead.review_count} kpl)")
    if lead.notes:
        parts.append(f"- Muistiinpanot: {lead.notes}")

    problem = describe_website_problem(lead.website_status, lead.website_issue)
    parts.append("")
    if problem:
        parts.append(f"HAVAINTO (varma, tein sen itse): {problem}")
        why = WHY_IT_MATTERS.get(lead.website_status or "")
        if why:
            parts.append(f"MIKSI SILLÄ ON VÄLIÄ (vihje): {why}")
    else:
        parts.append("HAVAINTO: ei varmistettua ongelmaa (älä väitä sivuston olevan rikki tai puutteellinen)")
    offer = DEMO_OFFER if has_demo else OFFERS.get(lead.website_status or "", DEFAULT_OFFER)
    parts.append(f"TARJOUS: {offer}")
    return parts


def build_email_user_prompt(
    lead: Lead, profile: SenderProfile, instruction: Optional[str] = None, *, has_demo: bool = False
) -> str:
    parts = _prompt_facts(lead, profile, has_demo=has_demo)
    if lead.website_context:
        parts.append(f"\nVERKKOSIVUN SISÄLTÖ (Deep Scan, käytä vain jos jotain konkreettista ja erityistä):\n{lead.website_context}")
    parts.append("\nKirjoita sähköposti tämän perusteella.")
    if instruction:
        parts.append(f"\nLisäohje: {instruction}")
    return "\n".join(parts)


def build_demo_email_user_prompt(lead: Lead, profile: SenderProfile, instruction: Optional[str] = None) -> str:
    parts = [
        "LÄHETTÄJÄ (minä):",
        f"- Nimi: {profile.name}",
        f"- Yritys: {profile.brand_name or profile.company_name or '(ei yritysnimeä, esiinny omalla nimellä)'}",
        f"- Esittely: {profile.short_intro}",
        "",
        "VASTAANOTTAJA:",
        f"- Yritys: {lead.name}",
        f"- Kaupunki: {lead.city}",
    ]
    if lead.primary_type:
        parts.append(f"- Toimiala (Googlen luokka englanniksi, käännä luontevasti suomeksi): {lead.primary_type}")
    problem = describe_website_problem(lead.website_status, lead.website_issue)
    parts.append("")
    if problem:
        parts.append(f"HAVAINTO (varma, tein sen itse): {problem}")
    else:
        parts.append("HAVAINTO: ei varmistettua ongelmaa (älä väitä sivuston olevan rikki tai puutteellinen)")
    parts.append(f"ASIAKKAAN TILANNE NYT (kappale 2): {customer_impact(lead.website_status, lead.website_issue)}")
    parts.append("\nKirjoita kappaleet 1 ja 2.")
    if instruction:
        parts.append(f"\nLisäohje: {instruction}")
    return "\n".join(parts)


def build_call_script_prompt(lead: Lead, profile: SenderProfile) -> str:
    parts = _prompt_facts(lead, profile)
    parts.append("\nKirjoita puhelinrunko tämän perusteella.")
    return "\n".join(parts)


def _get_contactable_lead(session: Session, lead_id: int, user: AuthUser) -> Lead:
    db_lead = session.get(Lead, lead_id)
    if not db_lead or db_lead.user_id != user.id:
        raise HTTPException(404, "Lead not found")
    if db_lead.do_not_contact:
        raise HTTPException(409, "Lead is marked do not contact")
    return db_lead


def _require_sender_profile(session: Session, user: AuthUser) -> SenderProfile:
    profile = get_sender_profile(session, user.id)
    if profile is None:
        # 428 Precondition Required: UI ohjaa täyttämään Settings-näkymän
        raise HTTPException(428, "Sender profile missing: fill in Settings before generating drafts")
    return profile


def chat_completion_params(model: str, reasoning_effort: str, max_tokens: int) -> Dict[str, object]:
    """Chat Completions -parametrit mallin tyypin mukaan (konfiguraatiosta, ei mallinimestä päätellen)."""
    params: Dict[str, object] = {"model": model, "max_completion_tokens": max_tokens}
    if reasoning_effort:
        params["reasoning_effort"] = reasoning_effort
    if reasoning_effort and reasoning_effort != "none":
        params["max_completion_tokens"] = max_tokens + REASONING_TOKEN_HEADROOM
    else:
        params["temperature"] = 0.7
    return params


class ChatResult(BaseModel):
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


async def _chat_completion(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    *,
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> ChatResult:
    """OpenAI-kutsu blokkaa -> taustasäikeeseen. Oletuksena EMAIL_MODEL-konfiguraatio."""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    params = chat_completion_params(
        model or EMAIL_MODEL,
        EMAIL_REASONING_EFFORT if reasoning_effort is None else reasoning_effort,
        max_tokens,
    )

    def _call():
        return client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **params,
        )

    response = await asyncio.to_thread(_call)
    usage = getattr(response, "usage", None)
    return ChatResult(
        text=(response.choices[0].message.content or "").strip(),
        model=response.model,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


# 6. GENEROI SÄHKÖPOSTI (AI)
@app.post("/leads/{lead_id}/generate-email", response_model=EmailGenerateResponse)
async def generate_email(
    lead_id: int,
    req: EmailGenerateRequest = EmailGenerateRequest(),
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    db_lead = _get_contactable_lead(session, lead_id, user)
    profile = _require_sender_profile(session, user)
    demo = get_published_demo(session, db_lead)
    if req.require_demo_link and demo is None:
        raise HTTPException(409, "Demo is not published: email with the demo link cannot be created")
    if not OPENAI_API_KEY:
        raise HTTPException(500, "OPENAI_API_KEY not configured")

    # Deep Scan: skraapataan verkkosivun teksti jos ei vielä cachessa
    if not db_lead.website_context and db_lead.website and db_lead.website_status != "NO WEBSITE":
        try:
            context = await asyncio.to_thread(scrape_website_text, db_lead.website)
            if context:
                db_lead.website_context = context
                db_lead.scraped_at = datetime.now(timezone.utc)
                session.add(db_lead)
                session.commit()
                session.refresh(db_lead)
                logger.info(f"Deep Scan: tallennettu {len(context)} merkkia kontekstia liidille {lead_id}")
        except Exception as e:
            logger.warning(f"Deep Scan epaonnistui liidille {lead_id}: {e}")

    demo_url = demo_public_url(demo) if demo else None
    if demo_url:
        # Malli kirjoittaa vain kappaleet 1–2, loput koodista (ks. build_demo_email_body)
        result = await _chat_completion(
            DEMO_EMAIL_SYSTEM_PROMPT, build_demo_email_user_prompt(db_lead, profile, req.instruction), max_tokens=300
        )
        model = result.model
        body = build_demo_email_body(result.text, profile, demo_url)
        check_generated_text(email_head(body), kind="sähköposti", lead_id=lead_id, model=model, max_words=DEMO_EMAIL_MAX_WORDS - 20)
        subject = demo_email_subject(db_lead)
    else:
        result = await _chat_completion(
            EMAIL_SYSTEM_PROMPT,
            build_email_user_prompt(db_lead, profile, req.instruction),
            max_tokens=500,
        )
        model = result.model
        text = strip_model_sign_off(result.text)
        check_generated_text(text, kind="sähköposti", lead_id=lead_id, model=model, max_words=MAX_EMAIL_WORDS)
        body = finalize_email_body(text, profile)
        subject = email_subject(db_lead)

    session.add(EmailDraft(user_id=user.id, lead_id=lead_id, subject=subject, body=body, model=model))
    session.commit()

    return EmailGenerateResponse(subject=subject, body=body, model=model)


@app.post("/leads/{lead_id}/email/demo-link", response_model=DemoLinkResponse)
def add_demo_link(
    lead_id: int,
    req: DemoLinkRequest,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    """Lisää julkaistun demon linkin jo kirjoitettuun luonnokseen (ei AI-kutsua)."""
    db_lead = _get_contactable_lead(session, lead_id, user)
    demo = get_published_demo(session, db_lead)
    url = demo_public_url(demo) if demo else None
    if demo is None or url is None:
        raise HTTPException(409, "Demo is not published: publish it before adding the link")
    return DemoLinkResponse(body=add_demo_link_to_body(req.body, url), demo_url=url)


# 6b. PUHELINSKRIPTI (AI)
@app.post("/leads/{lead_id}/generate-call-script", response_model=CallScriptResponse)
async def generate_call_script(
    lead_id: int,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    db_lead = _get_contactable_lead(session, lead_id, user)
    profile = _require_sender_profile(session, user)
    if not OPENAI_API_KEY:
        raise HTTPException(500, "OPENAI_API_KEY not configured")

    # Ei scrapingia: puhelu ei tarvitse jäänmurtajaa sivun sisällöstä
    result = await _chat_completion(
        CALL_SCRIPT_SYSTEM_PROMPT, build_call_script_prompt(db_lead, profile), max_tokens=450
    )
    model = result.model
    script = strip_markdown(result.text)
    check_generated_text(script, kind="puhelinskripti", lead_id=lead_id, model=model)
    return CallScriptResponse(script=script, model=model)


# --- DEMOSIVUT ---

# Hinnat per 1M tokenia (OpenAI-hinnasto 11/2026) kustannuslokia varten; tuntematon malli -> ei arviota
MODEL_PRICES_PER_1M: Dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-6.1-terra": (1.00, 5.00),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6-luna": (0.10, 0.50),
}
PLACE_DETAILS_ENTERPRISE_USD = 20.00 / 1000


class DemoGenerateRequest(BaseModel):
    template: Optional[str] = None
    color_scheme: Optional[str] = None


class DemoUpdateRequest(BaseModel):
    template: Optional[str] = None
    color_scheme: Optional[str] = None
    content: Optional[DemoContent] = None
    # Unsplash-kuvan id vaihtoehdoista (content.images.options) tai "none" = ei kuvaa (gradientti)
    hero_image_id: Optional[str] = None


class DemoOut(BaseModel):
    id: int
    lead_id: int
    template: str
    color_scheme: str
    content: DemoStoredContent
    public_token: str
    public_path: str  # julkisen osoitteen polku: slug, tai token ennen slugeja luoduilla demoilla
    preview_url: str  # backendin esikatselu (myös luonnokset)
    public_url: Optional[str] = None  # julkaistun demon osoite sähköpostiin
    publishing_enabled: bool = False
    status: str
    created_at: datetime
    published_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


def _demo_out(demo: Demo, request: Request) -> DemoOut:
    assert demo.id is not None
    return DemoOut(
        id=demo.id,
        lead_id=demo.lead_id,
        template=demo.template,
        color_scheme=demo.color_scheme,
        content=DemoStoredContent.model_validate_json(demo.content_json),
        public_token=demo.public_token,
        public_path=demo_path(demo),
        preview_url=f"{str(request.base_url).rstrip('/')}/demo/{demo_path(demo)}",
        public_url=demo_public_url(demo),
        publishing_enabled=get_r2_config() is not None,
        status=demo.status,
        created_at=demo.created_at,
        published_at=demo.published_at,
        expires_at=demo.expires_at,
    )


def _safe_web_url(url: Optional[str]) -> Optional[str]:
    # Vain http(s)-linkit demon banneriin (ei javascript: tms.)
    return url if url and url.lower().startswith(("http://", "https://")) else None


def _render_for(demo_template: str, scheme: str, content: DemoStoredContent, lead: Lead, profile: SenderProfile) -> str:
    return render_demo_html(
        template=demo_template,
        color_scheme=scheme,
        content=content,
        utm_app=UNSPLASH_APP_NAME,
        business=DemoBusiness(
            name=lead.name, city=lead.city, address=lead.address, phone=lead.phone,
            maps_url=_safe_web_url(lead.maps_url),
        ),
        sender=DemoSender(
            name=profile.name, company_name=profile.company_name, phone=profile.phone,
            website=_safe_web_url(profile.website),
        ),
    )


def _get_owned_demo(session: Session, lead_id: int, user: AuthUser) -> tuple[Lead, Demo]:
    lead = session.get(Lead, lead_id)
    if not lead or lead.user_id != user.id:
        raise HTTPException(404, "Lead not found")
    demo = session.exec(select(Demo).where(Demo.lead_id == lead_id, Demo.user_id == user.id)).first()
    if demo is None:
        raise HTTPException(404, "Demo not found")
    return lead, demo


def _can_fetch_place_details(lead: Lead) -> bool:
    return (
        USE_LIVE_GOOGLE
        and "AIza" in GOOGLE_API_KEY
        and bool(lead.google_place_id)
        and not (lead.google_place_id or "").startswith(("dev-", "manual-"))
    )


async def generate_demo_content(lead: Lead, template: str) -> tuple[DemoContent, list[ChatResult]]:
    """AI-sisältö, validointi ja yksi uudelleenyritys. Heittää DemoGenerationError jos ei kelpaa.

    Kovat virheet (skeema, keksityt faktat, kielletyt sanat) -> uudelleenyritys, toisellakin kerralla 502.
    Toistuvat fraasit ovat pehmeä virhe: ensimmäisellä kierroksella uudelleenyritys, toisella hyväksytään
    ja lokitetaan varoitus.
    """
    allowed_text = " ".join(filter(None, [lead.name, lead.city, lead.address, lead.website_context]))
    prompt = build_demo_prompt(
        name=lead.name, city=lead.city, primary_type=lead.primary_type, website_context=lead.website_context
    )
    results: list[ChatResult] = []
    problems: list[str] = []
    for attempt in range(2):
        result = await _chat_completion(
            DEMO_SYSTEM_PROMPT,
            prompt if attempt == 0 else retry_prompt(prompt, problems),
            max_tokens=1500,
            model=SITE_MODEL,
            reasoning_effort=SITE_REASONING_EFFORT,
        )
        results.append(result)
        content, problems = parse_ai_content(result.text, allowed_text=allowed_text)
        if content is not None:
            repeats = find_repeated_phrases(content, business_name=lead.name, template=template)
            if repeats and attempt == 0:
                problems = [f"toistuva fraasi '{r}' (mikään fraasi ei saa toistua sivulla)" for r in repeats]
                logger.info(f"Demosisällössä toistoa (liidi {lead.id}), uudelleenyritys: {repeats}")
                continue
            if repeats:
                logger.warning(f"Demo (liidi {lead.id}): toistuvat fraasit sivulla: {repeats}")
            return DemoContent(**content.model_dump()), results
        logger.warning(f"Demosisältö hylättiin (liidi {lead.id}, yritys {attempt + 1}/2): {problems[:5]}")
    raise DemoGenerationError("; ".join(problems[:10]))


async def find_demo_images(lead: Lead, template: str) -> tuple[DemoImages, int]:
    """(kuvat, Unsplash-hakujen määrä). Ilman avainta tai virheessä tyhjä -> gradientti."""
    if not UNSPLASH_ACCESS_KEY:
        return DemoImages(), 0
    queries = unsplash.image_queries(lead.primary_type, template)
    candidates = await asyncio.to_thread(unsplash.find_candidates, lead.primary_type, template, UNSPLASH_ACCESS_KEY)
    hero, mood, options = unsplash.choose_images(candidates, template)
    if unsplash.uses_both_queries(template):
        searches = len(queries[:2])
    else:
        searches = 1 if len(candidates) >= unsplash.MIN_CANDIDATES or len(queries) == 1 else 2
    return DemoImages(hero=hero, mood=mood, options=options), searches


def _track_downloads(photos: list[unsplash.DemoPhoto]) -> None:
    # Unsplashin vaatimus: lataustapahtuma kun kuva asetetaan sivulle. Ajetaan vastauksen jälkeen.
    for photo in photos:
        unsplash.track_download(photo, UNSPLASH_ACCESS_KEY)


def _used_photos(images: DemoImages) -> list[unsplash.DemoPhoto]:
    return ([images.hero] if images.hero else []) + list(images.mood)


def _log_demo_cost(lead_id: int, results: list[ChatResult], place_details_calls: int, unsplash_requests: int = 0) -> float:
    total = place_details_calls * PLACE_DETAILS_ENTERPRISE_USD
    for r in results:
        prices = next((p for name, p in MODEL_PRICES_PER_1M.items() if r.model.startswith(name)), None)
        if prices:
            total += r.input_tokens / 1e6 * prices[0] + r.output_tokens / 1e6 * prices[1]
    tokens = ", ".join(f"{r.model} in {r.input_tokens} / out {r.output_tokens}" for r in results)
    logger.info(
        f"Demo generoitu liidille {lead_id}: AI-kutsuja {len(results)} ({tokens}), "
        f"Place Details {place_details_calls} kpl ({PLACE_DETAILS_FIELD_MASK}), "
        f"Unsplash-pyyntöjä {unsplash_requests} (ilmainen API), arvio ~${total:.4f}"
    )
    return total


@app.get("/demo-templates")
def list_demo_templates(_user: AuthUser = Depends(verify_token)) -> list[dict[str, object]]:
    return templates_catalog()


@app.post("/leads/{lead_id}/demo", response_model=DemoOut)
async def generate_demo(
    lead_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    req: DemoGenerateRequest = DemoGenerateRequest(),
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    lead = _get_contactable_lead(session, lead_id, user)
    profile = _require_sender_profile(session, user)
    if not OPENAI_API_KEY:
        raise HTTPException(500, "OPENAI_API_KEY not configured")
    try:
        template, scheme = validate_template_choice(
            req.template or template_for_primary_type(lead.primary_type), req.color_scheme
        )
    except ValueError as e:
        raise HTTPException(422, str(e))

    try:
        content, results = await generate_demo_content(lead, template)
    except DemoGenerationError as e:
        raise HTTPException(502, f"Demo content failed validation: {e}")

    # Aukioloajat vasta nyt, yksi Place Details -kutsu (ei tallenneta erikseen, vain osana demoa)
    hours = None
    place_calls = 0
    if _can_fetch_place_details(lead) and lead.google_place_id:
        place_calls = 1
        hours = await asyncio.to_thread(fetch_opening_hours, lead.google_place_id, GOOGLE_API_KEY)
    images, searches = await find_demo_images(lead, template)
    stored = DemoStoredContent(
        **content.model_dump(exclude={"price_note"}),
        price_note=price_note_for(template),
        opening_hours=hours.descriptions if hours else [],
        opening_periods=hours.periods if hours else [],
        images=images,
    )
    used = _used_photos(images)
    if used:
        background_tasks.add_task(_track_downloads, used)
    _log_demo_cost(lead_id, results, place_calls, unsplash_requests=searches + len(used))

    html = _render_for(template, scheme, stored, lead, profile)
    demo = session.exec(select(Demo).where(Demo.lead_id == lead_id, Demo.user_id == user.id)).first()
    if demo is None:
        demo = Demo(
            user_id=user.id, lead_id=lead_id, template=template, color_scheme=scheme,
            content_json=stored.model_dump_json(), html=html, public_token=new_public_token(),
            public_slug=new_public_slug(lead.name, lambda slug: _demo_path_taken(session, slug)),
        )
    else:
        demo.template, demo.color_scheme = template, scheme
        demo.content_json, demo.html = stored.model_dump_json(), html
        if demo.status == "expired":
            demo.status, demo.expires_at, demo.published_at = "draft", None, None
        # Julkaistu demo päivittyy samaan osoitteeseen (sama slug/token)
        await asyncio.to_thread(_republish_if_published, demo)
    is_new = demo.id is None
    session.add(demo)
    try:
        session.commit()
    except IntegrityError:
        if not is_new:
            raise
        # Rinnakkainen luonti ehti varata saman osoitteen tarkistuksen jälkeen: uusi satunnaisosa
        session.rollback()
        demo.public_slug = new_public_slug(lead.name, lambda slug: _demo_path_taken(session, slug))
        session.add(demo)
        session.commit()
    session.refresh(demo)
    return _demo_out(demo, request)


@app.get("/leads/{lead_id}/demo", response_model=DemoOut)
def read_demo(
    lead_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    _, demo = _get_owned_demo(session, lead_id, user)
    return _demo_out(demo, request)


@app.patch("/leads/{lead_id}/demo", response_model=DemoOut)
def update_demo(
    lead_id: int,
    req: DemoUpdateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    """Pohjan/värien vaihto ja tekstien muokkaus ilman uutta AI-kutsua (renderöidään uudelleen)."""
    lead, demo = _get_owned_demo(session, lead_id, user)
    profile = _require_sender_profile(session, user)
    try:
        template, scheme = validate_template_choice(req.template or demo.template, req.color_scheme or (
            None if req.template and req.template != demo.template else demo.color_scheme
        ))
    except ValueError as e:
        raise HTTPException(422, str(e))

    stored = DemoStoredContent.model_validate_json(demo.content_json)
    if req.content is not None:
        stored = DemoStoredContent(
            **req.content.model_dump(), opening_hours=stored.opening_hours,
            opening_periods=stored.opening_periods, images=stored.images,
        )
    if template != demo.template and stored.price_note == price_note_for(demo.template):
        # Pohjan oletusteksti vaihtuu pohjan mukana (kahvilassa ei "ajanvarausta"); käyttäjän oma teksti säilyy
        stored = stored.model_copy(update={"price_note": price_note_for(template)})
    # Hero-vaihto, tai pohjan vaihto: tunnelmakuvien säännöt ovat pohjakohtaisia (kahvilassa tumma viimeinen)
    if req.hero_image_id is not None or template != demo.template:
        images = stored.images
        if req.hero_image_id is None:
            new_hero = images.hero
        elif req.hero_image_id == "none":
            new_hero = None
        else:
            new_hero = next((p for p in images.options if p.id == req.hero_image_id), None)
            if new_hero is None:
                raise HTTPException(422, "Unknown hero_image_id (must be one of content.images.options)")
        before = {p.id for p in _used_photos(images)}
        updated = DemoImages(hero=new_hero, mood=unsplash.mood_for(new_hero, images.options, template), options=images.options)
        stored = stored.model_copy(update={"images": updated})
        newly_used = [p for p in _used_photos(updated) if p.id not in before]
        if newly_used and UNSPLASH_ACCESS_KEY:
            background_tasks.add_task(_track_downloads, newly_used)

    demo.template, demo.color_scheme = template, scheme
    demo.content_json = stored.model_dump_json()
    demo.html = _render_for(template, scheme, stored, lead, profile)
    _republish_if_published(demo)
    session.add(demo)
    session.commit()
    session.refresh(demo)
    return _demo_out(demo, request)


# Puhelinnäkymän kuvakaappaukset: avain = HTML:n tiiviste, joten muutos tekee uuden kuvan
_SCREENSHOT_CACHE: OrderedDict[str, bytes] = OrderedDict()
SCREENSHOT_CACHE_SIZE = 30


@app.get("/leads/{lead_id}/demo/screenshot", include_in_schema=False)
async def demo_screenshot(
    lead_id: int,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
) -> Response:
    """390 px puhelinnäkymä JPEG:nä esikatselumodaaliin ennen julkaisua. 501 jos Playwright puuttuu."""
    _, demo = _get_owned_demo(session, lead_id, user)
    key = hashlib.sha256(demo.html.encode("utf-8")).hexdigest()
    image = _SCREENSHOT_CACHE.get(key)
    if image is None:
        try:
            image = await asyncio.to_thread(screenshot_demo, demo.html)
        except ScreenshotUnavailable as e:
            raise HTTPException(501, f"Screenshot not available: {e}")
        _SCREENSHOT_CACHE[key] = image
        while len(_SCREENSHOT_CACHE) > SCREENSHOT_CACHE_SIZE:
            _SCREENSHOT_CACHE.popitem(last=False)
    else:
        _SCREENSHOT_CACHE.move_to_end(key)
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@app.post("/leads/{lead_id}/demo/publish", response_model=DemoOut)
def publish_demo(
    lead_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    """Julkaisee demon R2:een: {DEMO_PUBLIC_BASE_URL}/{token}, vanhenee DEMO_TTL_DAYS päivän päästä."""
    lead, demo = _get_owned_demo(session, lead_id, user)
    if lead.do_not_contact:
        raise HTTPException(409, "Lead is marked do not contact")
    profile = _require_sender_profile(session, user)
    store = get_object_store()
    if store is None:
        raise HTTPException(503, "Publishing not configured (R2_* and DEMO_PUBLIC_BASE_URL in backend .env)")

    # Renderöidään tuoreena (esim. lähettäjäprofiilin yhteystiedot ovat voineet muuttua)
    stored = DemoStoredContent.model_validate_json(demo.content_json)
    demo.html = _render_for(demo.template, demo.color_scheme, stored, lead, profile)
    now = utc_now()
    expires_at = now + timedelta(days=DEMO_TTL_DAYS)
    try:
        publish_html(store, demo_path(demo), demo.html, expires_at, template_assets(demo.template))
    except PublishError as e:
        raise HTTPException(502, str(e))
    demo.status, demo.published_at, demo.expires_at = "published", now, expires_at
    session.add(demo)
    session.commit()
    session.refresh(demo)
    logger.info(f"Demo julkaistu (liidi {lead_id}), vanhenee {expires_at.date()}")
    return _demo_out(demo, request)


@app.post("/leads/{lead_id}/demo/unpublish", response_model=DemoOut)
def unpublish_demo(
    lead_id: int,
    request: Request,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    _, demo = _get_owned_demo(session, lead_id, user)
    if demo.status == "published":
        store = get_object_store()
        if store is None:
            raise HTTPException(503, "Publishing not configured (R2_* and DEMO_PUBLIC_BASE_URL in backend .env)")
        if not unpublish(store, demo_path(demo)):
            raise HTTPException(502, "R2 delete failed, try again")
    demo.status, demo.published_at, demo.expires_at = "draft", None, None
    session.add(demo)
    session.commit()
    session.refresh(demo)
    return _demo_out(demo, request)


@app.delete("/leads/{lead_id}/demo")
def delete_demo(
    lead_id: int,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    _, demo = _get_owned_demo(session, lead_id, user)
    _take_offline(demo)
    session.delete(demo)
    session.commit()
    return {"ok": True}


DEMO_RESPONSE_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    # Versio 1: staattinen, ei skriptejä, ei ulkoisia resursseja, inline-CSS sallittu
    # Kuvat hotlinkataan Unsplashista (API-ehto), fontit ovat inline data-URI:na
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data: https://images.unsplash.com; "
        "font-src data:; base-uri 'none'; form-action 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}
# Versio 2: omat CSS/JS/fontit samasta osoitteesta, ei inline-tyylejä eikä -skriptejä (sama kuin Workerissa)
DEMO_V2_RESPONSE_HEADERS = {
    **DEMO_RESPONSE_HEADERS,
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; script-src 'self'; font-src 'self'; "
        "img-src data: https://images.unsplash.com; base-uri 'none'; form-action 'none'"
    ),
}


@app.get("/demo/{public_path}", response_class=HTMLResponse, include_in_schema=False)
def view_demo(public_path: str, session: Session = Depends(get_session)) -> HTMLResponse:
    """Julkinen esikatselu ilman kirjautumista: slug (nimi + satunnainen osa) tai vanha token.

    Vain tarkka osuma; listausta tai osittaista hakua ei ole.
    """
    demo = session.exec(
        select(Demo).where(or_(Demo.public_slug == public_path, Demo.public_token == public_path))
    ).first()
    if demo is None:
        return HTMLResponse("Not found", status_code=404, headers=DEMO_RESPONSE_HEADERS)
    if demo.status == "expired" or (demo.expires_at and _as_utc(demo.expires_at) <= utc_now()):
        return HTMLResponse("Tämä luonnos ei ole enää saatavilla.", status_code=410, headers=DEMO_RESPONSE_HEADERS)
    headers = DEMO_V2_RESPONSE_HEADERS if is_v2_template(demo.template) else DEMO_RESPONSE_HEADERS
    return HTMLResponse(demo.html, headers=headers)


@app.get("/demo/a/{group}/{name}", include_in_schema=False)
def view_demo_asset(group: str, name: str) -> Response:
    """Version 2 demon CSS/JS/fontit esikatselua varten (Workerissa /a/...). Vain paketin tiedostot.

    CORS: esikatselu-iframe on sandboxattu (opaque origin), ja fontit ladataan aina CORS-tilassa.
    """
    asset = demo_asset(group, name)
    if asset is None:
        return Response("Not found", status_code=404, media_type="text/plain")
    return Response(
        asset.body,
        media_type=asset.content_type,
        headers={
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )

# 7. LÄHETÄ SÄHKÖPOSTI (SMTP)

class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    lead_id: Optional[int] = None


class SendEmailResponse(BaseModel):
    ok: bool
    message: str


@app.post("/send-email", response_model=SendEmailResponse)
async def send_email(
    req: SendEmailRequest,
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    if req.lead_id is not None:
        _get_contactable_lead(session, req.lead_id, user)
    # Estää lähetyksen myös ilman lead_id:tä, jos osoite kuuluu do-not-contact-liidille
    blocked = session.exec(
        select(Lead.id).where(
            Lead.user_id == user.id,
            Lead.do_not_contact == True,  # noqa: E712 (SQL-lauseke)
            func.lower(Lead.email) == req.to.strip().lower(),
        )
    ).first()
    if blocked is not None:
        raise HTTPException(409, "Recipient is marked do not contact")

    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM]):
        raise HTTPException(500, "SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD and SMTP_FROM in .env")

    cfg = SmtpConfig(host=SMTP_HOST, port=SMTP_PORT, user=SMTP_USER, password=SMTP_PASSWORD, from_addr=SMTP_FROM)
    msg = build_message(SMTP_FROM, req.to, req.subject, req.body)
    try:
        await asyncio.to_thread(send_mail, cfg, msg)
    except SmtpFailure as f:
        # Viesti on luokiteltu ja turvallinen (ei tunnuksia); sama teksti lokiin ja UI:hin
        logger.error(f"SMTP {f.kind} failure at {f.stage}: {f.user_message()}")
        raise HTTPException(502, f.user_message())

    return SendEmailResponse(ok=True, message=f"Email sent to {req.to}")
