# FILE: backend/app/main.py
import asyncio
import csv
import io
import logging
import smtplib
import threading
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import AsyncIterator, List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from urllib.parse import quote_plus, urlparse

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup

# Tuodaan omat moduulit
from .database import create_db_and_tables, get_session
from .models import Lead, LeadCreate, LeadUpdate, SearchHistoryEntry, EmailDraft, utc_now
from .utils.scraper import scrape_website_text
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
GRID_SIZE = 3              # 3x3 = 9 ruutua
MAX_PAGES_PER_CELL = 3     # Text Search (New): max 20/sivu, max 60 tulosta per kysely
MAX_WORKERS_WEBSITE = 5

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
class GoogleSearchResult(BaseModel):
    name: str
    place_id: str
    address: str
    phone: Optional[str] = None
    website: Optional[str] = None
    website_status: str
    discovery_method: str
    rating: Optional[float] = None
    review_count: Optional[int] = None
    business_status: Optional[str] = None
    primary_type: Optional[str] = None
    maps_url: Optional[str] = None


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


def drop_permanently_closed(places: List[Dict]) -> List[Dict]:
    # CLOSED_TEMPORARILY jätetään näkyviin (merkitään UI:ssa ja pisteytyksessä)
    return [p for p in places if p.get("business_status") != "CLOSED_PERMANENTLY"]


class GooglePlacesService:
    def __init__(self, api_key: str):
        self.key = api_key
        self._search_call_count = 0
        self._lock = threading.Lock()

    def _reserve_call(self) -> bool:
        """Varaa yhden kutsun budjetista. Lukko pitää rajan myös rinnakkaisissa kutsuissa."""
        with self._lock:
            if self._search_call_count >= MAX_SEARCH_CALLS:
                logger.warning(f"Search-kutsujen raja ({MAX_SEARCH_CALLS}) saavutettu — ohitetaan kutsu")
                return False
            self._search_call_count += 1
            return True

    @property
    def calls_used(self) -> int:
        with self._lock:
            return self._search_call_count

    def _get_json(self, url: str, params: Dict) -> Dict:
        if not self._reserve_call():
            return {}
        try:
            r = requests.get(url, params={**params, "key": self.key}, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"API Error ({url}): {e}")
            return {}

    def _post_json(self, url: str, body: Dict) -> Dict:
        if not self._reserve_call():
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
    def generate_grid_cells(viewport: Dict, grid_size: int = GRID_SIZE) -> List[Dict]:
        """Jakaa viewportin grid_size x grid_size suorakaiteeseen (locationRestriction.rectangle).

        Ruudut eivät limity: locationRestriction on tiukka raja, joten vierekkäiset
        suorakaiteet kattavat koko viewportin ilman aukkoja.
        """
        ne = viewport["northeast"]
        sw = viewport["southwest"]
        lat_step = (ne["lat"] - sw["lat"]) / grid_size
        lng_step = (ne["lng"] - sw["lng"]) / grid_size

        cells: List[Dict] = []
        for row in range(grid_size):
            for col in range(grid_size):
                cells.append({
                    "low": {
                        "latitude": sw["lat"] + lat_step * row,
                        "longitude": sw["lng"] + lng_step * col,
                    },
                    "high": {
                        "latitude": sw["lat"] + lat_step * (row + 1),
                        "longitude": sw["lng"] + lng_step * (col + 1),
                    },
                })
        return cells

    def search_cell(self, rectangle: Dict, keyword: str) -> List[Dict]:
        """Text Search (New) yhdelle ruudulle, max MAX_PAGES_PER_CELL sivua."""
        base_body: Dict = {
            "textQuery": keyword,
            "locationRestriction": {"rectangle": rectangle},
            "pageSize": 20,
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
        """Geocode → ruudukko → Text Search per ruutu → deduplikaatio → suljettujen suodatus."""
        viewport = self.get_city_bounds(city)
        if not viewport:
            logger.warning(f"Kaupungin '{city}' viewport-rajoja ei löytynyt")
            return []

        cells = self.generate_grid_cells(viewport)
        logger.info(f"Grid-haku: {len(cells)} ruutua, kaupunki='{city}', keyword='{keyword}'")

        unique: Dict[str, Dict] = {}
        for i, cell in enumerate(cells):
            places = self.search_cell(cell, keyword)
            before = len(unique)
            for place in places:
                normalized = normalize_place(place)
                if normalized["place_id"]:
                    unique[normalized["place_id"]] = normalized
            logger.info(
                f"  Ruutu {i+1}/{len(cells)}: {len(places)} tulosta, "
                f"{len(unique) - before} uutta (yhteensä {len(unique)} uniikkia)"
            )

        results = drop_permanently_closed(list(unique.values()))
        logger.info(
            f"Grid-haku valmis: {len(results)} yritystä "
            f"({len(unique) - len(results)} pysyvästi suljettua pois), "
            f"kutsuja käytetty: {self.calls_used}/{MAX_SEARCH_CALLS}"
        )
        return results

def analyze_website(url: str) -> str:
    if not url: return "NO WEBSITE"
    try:
        if not url.startswith("http"): url = f"http://{url}"
        r = requests.get(url, timeout=4, headers={'User-Agent': 'Googlebot/2.1'})
        if r.status_code >= 400: return "BROKEN WEBSITE"

        soup = BeautifulSoup(r.text, "html.parser")
        viewport = soup.find("meta", attrs={"name": "viewport"})
        if not viewport:
            return "NOT MOBILE"

        return "WEBSITE OK"
    except:
        return "BROKEN WEBSITE"

# --- ENDPOINTS ---

# 1. HAKU (Stateless, Google API)
# HUOM: Muutettu polku /leads -> /search, jotta /leads jää tietokannalle
def _mock_places(business_type: str, city: str) -> List[Dict]:
    """Dev-data: vaihtelevat arvot jotta pisteytys ja merkinnät näkyvät UI:ssa ilman API-kutsuja.

    (nimi, website, website_status, rating, review_count, business_status)
    """
    bt = business_type.title()
    rows: List[tuple] = [
        (f"{bt} Keskusta", None, "NO WEBSITE", 4.7, 132, "OPERATIONAL"),
        (f"{bt} Studio Aino", "www.example-aino.fi", "BROKEN WEBSITE", 4.4, 58, "OPERATIONAL"),
        (f"{bt} & Co", "www.example-co.fi", "NOT MOBILE", 4.1, 21, "OPERATIONAL"),
        (f"{bt} Express", "www.example-express.fi", "WEBSITE OK", 3.9, 240, "OPERATIONAL"),
        (f"Uusi {business_type}", None, "NO WEBSITE", None, 0, "OPERATIONAL"),
        (f"{bt} Kulma", None, "NO WEBSITE", 4.9, 12, "CLOSED_TEMPORARILY"),
        (f"Vanha {business_type}", None, "NO WEBSITE", 3.2, 7, "CLOSED_PERMANENTLY"),
        (f"{bt} Premium", "www.example-premium.fi", "WEBSITE OK", 4.8, 410, "OPERATIONAL"),
    ]
    return [
        {
            "place_id": f"dev-{i}",
            "name": name,
            "address": f"Esimerkkikatu {i}, {city}",
            "phone": f"040 123 45{i:02d}" if i % 3 else None,
            "website": website,
            "website_status": status,
            "rating": rating,
            "review_count": reviews,
            "business_status": business_status,
            "primary_type": None,
            "maps_url": f"https://www.google.com/maps/search/?api=1&query={quote_plus(f'{name} {city}')}",
        }
        for i, (name, website, status, rating, reviews, business_status) in enumerate(rows, start=1)
    ]


# 1. HAKU (Stateless, Google API)
# HUOM: Muutettu polku /leads -> /search, jotta /leads jää tietokannalle
@app.get("/search", response_model=List[GoogleSearchResult])
async def search_google(
    business_type: str = Query(..., min_length=2),
    city: str = Query(..., min_length=2),
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    if not USE_LIVE_GOOGLE:
        places = drop_permanently_closed(_mock_places(business_type, city))
        results = [GoogleSearchResult(**p, discovery_method="DEV-MOCK") for p in places]
        session.add(SearchHistoryEntry(user_id=user.id, business_type=business_type, city=city, result_count=len(results)))
        session.commit()
        return results

    if "AIza" not in GOOGLE_API_KEY:
        raise HTTPException(500, "API Key missing")

    service = GooglePlacesService(GOOGLE_API_KEY)

    # Google-kutsut ja website-analyysi blokkaavat -> taustasäikeeseen, event loop ei jäädy
    places = await asyncio.to_thread(service.search_grid, city, business_type)
    if not places:
        return []

    def _blocking_website_analysis() -> List[GoogleSearchResult]:
        output = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS_WEBSITE) as ex:
            future_map = {ex.submit(analyze_website, p.get("website")): p for p in places}
            for f in as_completed(future_map):
                output.append(GoogleSearchResult(
                    **future_map[f],
                    website_status=f.result(),
                    discovery_method="API",
                ))
        return output

    results = await asyncio.to_thread(_blocking_website_analysis)
    session.add(SearchHistoryEntry(user_id=user.id, business_type=business_type, city=city, result_count=len(results)))
    session.commit()
    return results

# 2. TALLENNA LIIDI (Database)
@app.post("/leads", response_model=Lead)
def create_lead(
    lead: LeadCreate,
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

    db_lead = Lead.model_validate(lead, update={"user_id": user.id})
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

EMAIL_SYSTEM_PROMPT = """Olet B2B-myyntiavustaja suomalaiselle web-kehitysyritykselle.

Kirjoita lyhyt, rento ja suora sähköposti potentiaaliselle asiakkaalle.
Sähköpostin pitää tuntua henkilökohtaiselta — ei massaviestiltä.

SÄÄNNÖT:
- Kieli: suomi
- Pituus: max 6 lausetta (tervehdys + 2-3 lausetta asiaa + ehdotus + lopetus)
- Sävy: ystävällinen, asiantunteva, EI painostava
- Älä käytä sanoja "ainutlaatuinen", "mahtava", "upea" tai muuta kliseistä mainosjargonia
- Älä lupaa mitään konkreettista (hintaa, aikataulua) — tavoite on saada vastaus
- Mainitse löydetty ongelma luontevasti, älä haukkuen
- Allekirjoitus: jätä pois, käyttäjä lisää oman
- Palauta VAIN sähköpostin teksti, ei subject-riviä erikseen

ONGELMIEN KUVAUKSET:
- NO WEBSITE: yrityksellä ei ole nettisivuja lainkaan
- BROKEN WEBSITE: nettisivu ei toimi tai antaa virheen
- NOT MOBILE: nettisivu toimii mutta ei skaalaudu mobiililaitteille
- WEBSITE OK: sivu toimii hyvin — keskity muuhun lisäarvoon (esim. näkyvyys, päivitys)

DEEP SCAN (jos VERKKOSIVUN SISÄLTÖ on annettu):
- Aloita sähköposti lyhyellä, personoidulla jäänmurtajalla (1-2 lausetta) joka viittaa suoraan yrityksen verkkosivulta löytyneeseen konkreettiseen asiaan (esim. palvelu, arvo, saavutus, erikoisuus)
- Jäänmurtajan pitää osoittaa että olet oikeasti tutustunut yritykseen — ei geneerisiä fraaseja
- Siirry sen jälkeen luontevasti varsinaiseen asiaan (nettisivujen ongelma tai kehitysehdotus)
- Jos verkkosivun sisältö ei ole saatavilla, kirjoita meili normaalisti ilman jäänmurtajaa"""

class EmailGenerateRequest(BaseModel):
    instruction: Optional[str] = None

class EmailGenerateResponse(BaseModel):
    subject: str
    body: str
    model: str

def build_email_user_prompt(lead: Lead, instruction: Optional[str] = None) -> str:
    parts = [
        f"Yritys: {lead.name}",
        f"Kaupunki: {lead.city}",
    ]
    if lead.website:
        parts.append(f"Nettisivu: {lead.website}")
    if lead.website_status:
        parts.append(f"Nettisivun tila: {lead.website_status}")
    if lead.website_context:
        parts.append(f"\nVERKKOSIVUN SISÄLTÖ (Deep Scan):\n{lead.website_context}")
    if lead.notes:
        parts.append(f"Muistiinpanot: {lead.notes}")

    parts.append("\nKirjoita sähköposti tämän perusteella.")

    if instruction:
        parts.append(f"\nLisäohje: {instruction}")

    return "\n".join(parts)

# 6. GENEROI SÄHKÖPOSTI (AI)
@app.post("/leads/{lead_id}/generate-email", response_model=EmailGenerateResponse)
async def generate_email(
    lead_id: int,
    req: EmailGenerateRequest = EmailGenerateRequest(),
    session: Session = Depends(get_session),
    user: AuthUser = Depends(verify_token),
):
    if not OPENAI_API_KEY:
        raise HTTPException(500, "OPENAI_API_KEY not configured")

    db_lead = session.get(Lead, lead_id)
    if not db_lead or db_lead.user_id != user.id:
        raise HTTPException(404, "Lead not found")

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

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    user_prompt = build_email_user_prompt(db_lead, req.instruction)

    def _call_openai():
        return client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": EMAIL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
            temperature=0.7,
        )

    response = await asyncio.to_thread(_call_openai)
    body = response.choices[0].message.content.strip()

    # Generoi subject-rivi liidin tietojen perusteella
    status_subjects = {
        "NO WEBSITE": f"Nettisivut yritykselle {db_lead.name}?",
        "BROKEN WEBSITE": f"Huomasimme ongelman sivuillanne — {db_lead.name}",
        "NOT MOBILE": f"Mobiiliystävällisyys — {db_lead.name}",
        "WEBSITE OK": f"Nettinäkyvyyden kehittäminen — {db_lead.name}",
    }
    subject = status_subjects.get(db_lead.website_status or "", f"Yhteistyöehdotus — {db_lead.name}")

    # Tallenna draft kantaan
    session.add(EmailDraft(user_id=user.id, lead_id=lead_id, subject=subject, body=body, model=response.model))
    session.commit()

    return EmailGenerateResponse(
        subject=subject,
        body=body,
        model=response.model,
    )

# 7. LÄHETÄ SÄHKÖPOSTI (SMTP)

class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str

class SendEmailResponse(BaseModel):
    ok: bool
    message: str

@app.post("/send-email", response_model=SendEmailResponse)
async def send_email(
    req: SendEmailRequest,
    _user: AuthUser = Depends(verify_token),
):
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