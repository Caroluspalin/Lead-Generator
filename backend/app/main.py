# FILE: backend/app/main.py
import asyncio
import csv
import io
import logging
import re
import smtplib
import threading
import unicodedata
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import deque
from typing import AsyncIterator, List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from urllib.parse import quote_plus, urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine, func
from sqlmodel import Session, select
from pydantic import BaseModel
import requests

# Tuodaan omat moduulit
from .database import create_db_and_tables, get_session
from .models import (
    Lead, LeadCreate, LeadUpdate, SearchHistoryEntry, EmailDraft, SenderProfile, SenderProfileUpdate, utc_now,
)
from .utils.scraper import scrape_website_text
from .utils.website_check import analyze_website
from .utils.contact_finder import find_contact_email
from .scoring import lead_score
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
MAX_WORKERS_WEBSITE = 5

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

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tietokannan alustus käynnistyessä
    create_db_and_tables()
    yield


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


class SearchResponse(BaseModel):
    results: List[GoogleSearchResult]
    usage: SearchUsage


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

    def search_cell(self, rectangle: Dict, keyword: str) -> List[Dict]:
        """Text Search (New) yhdelle ruudulle, max MAX_PAGES_PER_CELL sivua."""
        base_body: Dict = {
            "textQuery": keyword,
            "locationRestriction": {"rectangle": rectangle},
            "pageSize": PAGE_SIZE,
            "languageCode": "fi",
            "regionCode": "FI",
        }
        all_places: List[Dict] = []
        page_token: Optional[str] = None

        for _ in range(MAX_PAGES_PER_CELL):
            # Googlen ehto: sivutuspyynnön muiden parametrien pitää olla identtiset
            body = {**base_body, "pageToken": page_token} if page_token else base_body
            data = self._post_json(PLACES_TEXT_SEARCH_URL, body)
            all_places.extend(data.get("places", []))

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return all_places

    def search_grid(self, city: str, keyword: str) -> List[Dict]:
        """Mukautuva ruudukko: koko kaupunki yhdellä kyselyllä, jaetaan vain täyttyneet alueet.

        Text Search palauttaa max 60 tulosta per kysely. Jos alue täyttyy, siellä voi olla
        lisää yrityksiä -> jaetaan 2x2 ja haetaan neljännekset (leveyshaku, max MAX_SPLIT_DEPTH).
        MAX_SEARCH_CALLS katkaisee haun aina.
        """
        viewport = self.get_city_bounds(city)
        if not viewport:
            logger.warning(f"Kaupungin '{city}' viewport-rajoja ei löytynyt")
            return []

        unique: Dict[str, Dict] = {}
        queue: deque[tuple[Dict, int]] = deque([(self.viewport_to_rectangle(viewport), 0)])
        areas = 0
        while queue:
            if self.calls_used >= MAX_SEARCH_CALLS:
                logger.warning(f"Kutsuraja täynnä, {len(queue)} aluetta jäi hakematta")
                break
            rect, depth = queue.popleft()
            places = self.search_cell(rect, keyword)
            areas += 1
            before = len(unique)
            for place in places:
                normalized = normalize_place(place)
                if normalized["place_id"]:
                    unique[normalized["place_id"]] = normalized
            saturated = len(places) >= MAX_RESULTS_PER_QUERY
            logger.info(
                f"  Alue {areas} (taso {depth}): {len(places)} tulosta, {len(unique) - before} uutta"
                f"{' — täynnä, jaetaan' if saturated and depth < MAX_SPLIT_DEPTH else ''}"
            )
            if saturated and depth < MAX_SPLIT_DEPTH:
                queue.extend((q, depth + 1) for q in self.split_rectangle(rect))

        open_places = drop_permanently_closed(list(unique.values()))
        results = merge_duplicates(open_places)
        usage = self.usage()
        logger.info(
            f"Haku valmis: '{keyword}' / '{city}': {len(results)} yritystä "
            f"({len(unique) - len(open_places)} pysyvästi suljettua pois, "
            f"{len(open_places) - len(results)} duplikaattia yhdistetty), {areas} aluetta, "
            f"{usage.api_calls}/{MAX_SEARCH_CALLS} kutsua "
            f"(geocode {usage.geocode_calls}, text search {usage.text_search_calls}), "
            f"~${usage.estimated_cost_usd:.3f}"
        )
        return results

# --- ENDPOINTS ---

def _mock_places(business_type: str, city: str) -> List[Dict]:
    """Dev-data: vaihtelevat arvot jotta pisteytys ja merkinnät näkyvät UI:ssa ilman API-kutsuja."""
    bt = business_type.title()
    # (nimi, website, website_status, website_issue, rating, review_count, business_status)
    rows: List[tuple] = [
        (f"{bt} Keskusta", None, "NO WEBSITE", None, 4.7, 132, "OPERATIONAL"),
        (f"{bt} Studio Aino", "www.example-aino.fi", "BROKEN WEBSITE", "HTTP 500", 4.4, 58, "OPERATIONAL"),
        (f"{bt} Vanhatalo", "www.example-vanhatalo.fi", "INSECURE", "SSL certificate expired", 4.6, 87, "OPERATIONAL"),
        (f"{bt} & Co", "www.example-co.fi", "NOT MOBILE", "no viewport meta", 4.1, 21, "OPERATIONAL"),
        (f"{bt} Express", "www.example-express.fi", "WEBSITE OK", None, 3.9, 240, "OPERATIONAL"),
        (f"Uusi {business_type}", None, "NO WEBSITE", None, None, 0, "OPERATIONAL"),
        (f"{bt} Kulma", None, "NO WEBSITE", None, 4.9, 12, "CLOSED_TEMPORARILY"),
        (f"Vanha {business_type}", None, "NO WEBSITE", None, 3.2, 7, "CLOSED_PERMANENTLY"),
        (f"{bt} Premium", "www.example-premium.fi", "WEBSITE OK", None, 4.8, 410, "OPERATIONAL"),
        (f"{bt} Linna", "www.example-linna.fi", "UNKNOWN", "HTTP 403", 4.5, 64, "OPERATIONAL"),
    ]
    return [
        {
            "place_id": f"dev-{i}",
            "name": name,
            "address": f"Esimerkkikatu {i}, {city}",
            "phone": f"040 123 45{i:02d}" if i % 3 else None,
            "website": website,
            "website_status": status,
            "website_issue": issue,
            "rating": rating,
            "review_count": reviews,
            "business_status": business_status,
            "primary_type": None,
            "maps_url": f"https://www.google.com/maps/search/?api=1&query={quote_plus(f'{name} {city}')}",
        }
        for i, (name, website, status, issue, rating, reviews, business_status) in enumerate(rows, start=1)
    ]


def _finalize_search(
    results: List[GoogleSearchResult],
    business_type: str,
    city: str,
    session: Session,
    user: AuthUser,
    usage: SearchUsage,
) -> SearchResponse:
    """Pisteyttää, merkitsee jo tallennetut, järjestää (paras ensin) ja tallentaa hakuhistorian."""
    saved_ids = set(session.exec(
        select(Lead.google_place_id).where(
            Lead.user_id == user.id,
            Lead.google_place_id.in_([r.place_id for r in results]),
        )
    ).all())
    for r in results:
        r.lead_score = lead_score(r.website_status, r.rating, r.review_count, r.business_status)
        r.already_saved = r.place_id in saved_ids
    results.sort(key=lambda r: (-r.lead_score, r.name))

    session.add(SearchHistoryEntry(user_id=user.id, business_type=business_type, city=city, result_count=len(results)))
    session.commit()
    return SearchResponse(results=results, usage=usage)


# 1. HAKU (Stateless, Google API)
# HUOM: Muutettu polku /leads -> /search, jotta /leads jää tietokannalle
@app.get("/search", response_model=SearchResponse)
async def search_google(
    business_type: str = Query(..., min_length=2),
    city: str = Query(..., min_length=2),
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    if not USE_LIVE_GOOGLE:
        places = drop_permanently_closed(_mock_places(business_type, city))
        results = [GoogleSearchResult(**p, discovery_method="DEV-MOCK") for p in places]
        return _finalize_search(results, business_type, city, session, user, SearchUsage())

    if "AIza" not in GOOGLE_API_KEY:
        raise HTTPException(500, "API Key missing")

    service = GooglePlacesService(GOOGLE_API_KEY)

    # Google-kutsut ja website-analyysi blokkaavat -> taustasäikeeseen, event loop ei jäädy
    places = await asyncio.to_thread(service.search_grid, city, business_type)

    def _blocking_website_analysis() -> List[GoogleSearchResult]:
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

    results = await asyncio.to_thread(_blocking_website_analysis) if places else []
    return _finalize_search(results, business_type, city, session, user, service.usage())

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
    session.delete(db_lead)
    session.commit()
    return {"ok": True}

# --- AI EMAIL SERVICE ---

# Sähköpostien ja puhelinskriptien malli. gpt-4o-mini poistuu OpenAI:lta 14.1.2027 (deprecations-sivu).
EMAIL_MODEL = os.getenv("EMAIL_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
# Reasoning-malleille (GPT-6-sarja): none | low | medium | high. Tyhjä = ei reasoning-parametria (gpt-4o-mini).
# OpenAI: temperature on sallittu vain kun reasoning effort on "none" tai mallilla ei ole reasoningia.
EMAIL_REASONING_EFFORT = os.getenv("EMAIL_REASONING_EFFORT", "").strip().lower()
# Reasoning-tokenit lasketaan max_completion_tokens-rajaan -> lisävara, ettei vastaus katkea tyhjäksi
REASONING_TOKEN_HEADROOM = 4000

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

# Kielletyt sanat/fraasit: (näytettävä nimi, regex). Taivutusmuodot mukana; "ihan" ei osu "ihana"-kuvioon.
FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in [
        ("ihana", r"\bihan(a|aa|an|at|ia|ista|imp)\w*"),
        ("upea", r"\bupe(a|i)\w*"),
        ("mahtava", r"\bmahtav\w*"),
        ("ainutlaatuinen", r"\bainutlaatui\w*"),
        ("intohimo", r"\bintohimo\w*"),
        ("ratkaisu", r"\bratkaisu\w*"),
        ("kokonaisvaltainen", r"\bkokonaisvaltai\w*"),
        ("digitaalinen läsnäolo", r"\bdigitaali\w*\s+läsnäolo\w*"),
        ("nostaa seuraavalle tasolle", r"\b(seuraavalle|uudelle)\s+tasolle\b"),
        ("innovatiivinen", r"\binnovatiivi\w*"),
        ("räätälöity", r"\bräätälöi\w*"),
        ("huippu", r"\bhuippu\w*"),
        ("saumaton", r"\bsaumat\w*"),
        ("synergia", r"\bsynergi\w*"),
        ("keskustella tarkemmin", r"\bkeskustel\w*\s+(asiasta\s+)?tarkemmin\b"),
        ("liiketoiminnan kasvu", r"\bliiketoimin\w*\s+kasv\w*"),
        ("saattaa (arvailu)", r"\bsaatta(a|vat|isi)\b"),
    ]
]
PRICE_RE = re.compile(r"\d[\d\s.,]*\s*(€|e\b|euro)", re.IGNORECASE)

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


def find_forbidden_words(text: str) -> list[str]:
    return [label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(text)]


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


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


def build_signature(profile: SenderProfile) -> str:
    lines = [profile.name, profile.company_name, profile.phone, profile.website]
    return "\n".join(line for line in lines if line)


def strip_model_sign_off(text: str) -> str:
    """Poistaa mallin mahdollisesti kirjoittaman lopputervehdyksen/allekirjoituksen (koodi lisää oman)."""
    lines = text.rstrip().splitlines()
    for i in range(len(lines) - 1, max(-1, len(lines) - 6), -1):
        if _SIGN_OFF_RE.match(lines[i]) or "[nimesi]" in lines[i].lower():
            lines = lines[:i]
    return "\n".join(lines).rstrip()


def finalize_email_body(text: str, profile: SenderProfile) -> str:
    return f"{strip_model_sign_off(text)}\n\n{SIGN_OFF}\n{build_signature(profile)}\n\n{OPT_OUT_LINE}"


EMAIL_SYSTEM_PROMPT = f"""Kirjoitat suomeksi lyhyen ensimmäisen yhteydenoton sähköpostin paikalliselle yritykselle.
Lähettäjä on yksityinen tekijä (tiedot LÄHETTÄJÄ-kohdassa). Viestin pitää kuulostaa oikealta ihmiseltä, joka on
oikeasti katsonut yrityksen tiedot — ei markkinointiviestiltä.

PAKOLLISET SÄÄNNÖT:
1. Te-muoto johdonmukaisesti koko viestissä (teidän, teille, sivunne, voitte). Ei koskaan sinä-muotoa.
2. Aloita "Hei," ja heti ensimmäinen lause kertoo kuka olen ja miten löysin yrityksen,
   esim. "Olen Palin ja teen nettisivuja paikallisille yrityksille. Etsin parturi-kampaamoja Kauniaisista ja huomasin, että..."
   Käytä LÄHETTÄJÄ-kohdan nimeä ja esittelyä, toimialaa ja kaupunkia (taivuta luontevasti).
3. HAVAINTO kerrotaan omana, varmana havaintona konkreettisesti (esim. "Kun avasin sivunne, selain varoitti...",
   "Googlen kautta löytyvä osoitteenne ei avaudu", "Löysin teidät vain Facebookista").
   Älä arvaile ("saattaa", "voi olla") kun havainto on annettu.
   Jos havaintoa ei ole annettu, älä keksi ongelmaa.
4. Yksi lause siitä, miksi sillä on väliä heidän asiakkailleen (käytä vihjettä). Ei pelottelua, ei liioittelua.
5. Tarjous: käytä TARJOUS-kohdan lausetta (voit muotoilla hieman). Pieni ja konkreettinen.
   Älä ehdota "keskustelua tarkemmin" tai palaveria.
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
- Ei teknistä jargonia, ei liioittelua, ei pelottelua, ei kiellettyjä sanoja
  (ihana, upea, mahtava, ainutlaatuinen, intohimo, ratkaisu, kokonaisvaltainen, digitaalinen läsnäolo, seuraavalle tasolle).
- Palauta vain runko otsikoineen."""


class EmailGenerateRequest(BaseModel):
    instruction: Optional[str] = None


class EmailGenerateResponse(BaseModel):
    subject: str
    body: str
    model: str


class CallScriptResponse(BaseModel):
    script: str
    model: str


def _prompt_facts(lead: Lead, profile: SenderProfile) -> list[str]:
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
    parts.append(f"TARJOUS: {OFFERS.get(lead.website_status or '', DEFAULT_OFFER)}")
    return parts


def build_email_user_prompt(lead: Lead, profile: SenderProfile, instruction: Optional[str] = None) -> str:
    parts = _prompt_facts(lead, profile)
    if lead.website_context:
        parts.append(f"\nVERKKOSIVUN SISÄLTÖ (Deep Scan, käytä vain jos jotain konkreettista ja erityistä):\n{lead.website_context}")
    parts.append("\nKirjoita sähköposti tämän perusteella.")
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


async def _chat_completion(system_prompt: str, user_prompt: str, max_tokens: int) -> tuple[str, str]:
    """Palauttaa (teksti, malli). OpenAI-kutsu blokkaa -> taustasäikeeseen."""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    params = chat_completion_params(EMAIL_MODEL, EMAIL_REASONING_EFFORT, max_tokens)

    def _call():
        return client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **params,
        )

    response = await asyncio.to_thread(_call)
    return (response.choices[0].message.content or "").strip(), response.model


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

    text, model = await _chat_completion(
        EMAIL_SYSTEM_PROMPT, build_email_user_prompt(db_lead, profile, req.instruction), max_tokens=500
    )
    text = strip_model_sign_off(text)
    check_generated_text(text, kind="sähköposti", lead_id=lead_id, model=model, max_words=MAX_EMAIL_WORDS)
    body = finalize_email_body(text, profile)
    subject = email_subject(db_lead)

    session.add(EmailDraft(user_id=user.id, lead_id=lead_id, subject=subject, body=body, model=model))
    session.commit()

    return EmailGenerateResponse(subject=subject, body=body, model=model)


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
    script, model = await _chat_completion(
        CALL_SCRIPT_SYSTEM_PROMPT, build_call_script_prompt(db_lead, profile), max_tokens=450
    )
    check_generated_text(script, kind="puhelinskripti", lead_id=lead_id, model=model)
    return CallScriptResponse(script=script, model=model)


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

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = req.to
    msg["Subject"] = req.subject
    msg.attach(MIMEText(req.body, "plain", "utf-8"))

    def _send():
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

    try:
        await asyncio.to_thread(_send)
    except Exception as e:
        logger.error(f"SMTP error: {e}")
        raise HTTPException(500, f"Email sending failed: {e}")

    return SendEmailResponse(ok=True, message=f"Email sent to {req.to}")
