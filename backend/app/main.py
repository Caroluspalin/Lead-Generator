# FILE: backend/app/main.py
import asyncio
import logging
import time
from typing import List, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup

# Tuodaan omat moduulit
from .database import create_db_and_tables, get_session
from .models import Lead, LeadCreate, LeadUpdate

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

# Safety Limits
MAX_SEARCH_CALLS = 15    # Geocode + Nearby Search + paginointi yhteensä
MAX_DETAIL_CALLS = 40    # Place Details -kutsut (1 per uniikki yritys)
GRID_SIZE = 3              # 3x3 = 9 ruutua
GRID_OVERLAP_FACTOR = 1.2  # 20% limittyminen ruutujen välillä
MAX_WORKERS_WEBSITE = 5

# URL Config
BASE_URL = "https://maps.googleapis.com/maps/api/place"
TEXT_SEARCH_URL = f"{BASE_URL}/textsearch/json"
NEARBY_SEARCH_URL = f"{BASE_URL}/nearbysearch/json"
DETAILS_URL = f"{BASE_URL}/details/json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Load USE_LIVE_GOOGLE from environment (defaults to False)
USE_LIVE_GOOGLE = os.getenv("USE_LIVE_GOOGLE", "False").lower() == "true"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# App Initialization
app = FastAPI(title="Agency Hunter CRM", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tietokannan alustus käynnistyessä
@app.on_event("startup")
def on_startup():
    create_db_and_tables()

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

class GooglePlacesService:
    def __init__(self, api_key: str):
        self.key = api_key
        self._search_call_count = 0
        self._detail_call_count = 0

    def _make_request(self, url: str, params: Dict, *, call_type: str = "search") -> Dict:
        """Tekee API-kutsun ja tarkistaa turvarajan ennen kutsua.

        call_type: "search" (geocode, nearby/text search) tai "detail" (place details).
        """
        if call_type == "search":
            if self._search_call_count >= MAX_SEARCH_CALLS:
                logger.warning(f"Search-kutsujen raja ({MAX_SEARCH_CALLS}) saavutettu — ohitetaan kutsu")
                return {}
            self._search_call_count += 1
        elif call_type == "detail":
            if self._detail_call_count >= MAX_DETAIL_CALLS:
                logger.warning(f"Detail-kutsujen raja ({MAX_DETAIL_CALLS}) saavutettu — ohitetaan kutsu")
                return {}
            self._detail_call_count += 1

        params["key"] = self.key
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"API Error: {e}")
            return {}

    # --- Grid-haku ---

    def get_city_bounds(self, city_name: str) -> Optional[Dict]:
        """Hakee kaupungin viewport-rajat Geocode API:lla (1 search-kutsu)."""
        data = self._make_request(GEOCODE_URL, {"address": f"{city_name}, Finland"}, call_type="search")
        if not data.get("results"):
            return None
        return data["results"][0]["geometry"].get("viewport")

    @staticmethod
    def generate_grid_points(viewport: Dict, grid_size: int = GRID_SIZE) -> tuple:
        """Jakaa viewportin grid_size x grid_size ruudukkoon.

        Palauttaa (points, radius_meters):
          - points: [{"lat": float, "lng": float}, ...]
          - radius_meters: dynaaminen säde metreinä, laskettu viewportista
        """
        import math

        ne = viewport["northeast"]
        sw = viewport["southwest"]

        # Lasketaan viewportin fyysinen koko metreinä (Haversine-approksimaatio)
        lat_mid = (ne["lat"] + sw["lat"]) / 2
        lat_span_m = (ne["lat"] - sw["lat"]) * 111_320  # 1° lat ≈ 111.32 km
        lng_span_m = (ne["lng"] - sw["lng"]) * 111_320 * math.cos(math.radians(lat_mid))

        # Yhden ruudun diagonaalin puolikas = säde joka peittää ruudun
        # Kerrotaan GRID_OVERLAP_FACTOR:lla niin ruudut limittyvät hieman
        cell_lat_m = lat_span_m / grid_size
        cell_lng_m = lng_span_m / grid_size
        cell_diagonal = math.sqrt(cell_lat_m**2 + cell_lng_m**2)
        radius_m = int((cell_diagonal / 2) * GRID_OVERLAP_FACTOR)

        # Google Nearby Search max radius = 50 000 m
        radius_m = min(radius_m, 50_000)

        lat_step = (ne["lat"] - sw["lat"]) / grid_size
        lng_step = (ne["lng"] - sw["lng"]) / grid_size

        points = []
        for row in range(grid_size):
            for col in range(grid_size):
                center_lat = sw["lat"] + lat_step * (row + 0.5)
                center_lng = sw["lng"] + lng_step * (col + 0.5)
                points.append({"lat": center_lat, "lng": center_lng})

        return points, radius_m

    def search_nearby_pagination(self, lat: float, lng: float, keyword: str, radius: int) -> List[Dict]:
        """Nearby Search yhdelle ruudukon pisteelle, max 3 sivua paginointia."""
        all_results: List[Dict] = []
        next_token = None

        for _ in range(3):  # Googlen max 3 sivua = 60 tulosta
            params: Dict = {
                "location": f"{lat},{lng}",
                "radius": radius,
                "keyword": keyword,
            }
            if next_token:
                params["pagetoken"] = next_token
                time.sleep(2)  # Google vaatii ~2s viiveen next_page_token:lle

            data = self._make_request(NEARBY_SEARCH_URL, params, call_type="search")
            results = data.get("results", [])
            all_results.extend(results)

            next_token = data.get("next_page_token")
            if not next_token:
                break

        return all_results

    def search_grid(self, city: str, keyword: str) -> Dict[str, Dict]:
        """Suorittaa koko grid-haun: geocode → ruudukko → nearby search → deduplikaatio.

        Palauttaa: {place_id: place_dict} — deduplikoitu dict.
        """
        viewport = self.get_city_bounds(city)
        if not viewport:
            logger.warning(f"Kaupungin '{city}' viewport-rajoja ei löytynyt")
            return {}

        grid_points, radius_m = self.generate_grid_points(viewport)
        logger.info(
            f"Grid-haku: {len(grid_points)} ruutua, säde {radius_m}m, "
            f"kaupunki='{city}', keyword='{keyword}'"
        )

        unique_places: Dict[str, Dict] = {}

        for i, point in enumerate(grid_points):
            results = self.search_nearby_pagination(point["lat"], point["lng"], keyword, radius_m)
            before = len(unique_places)
            for place in results:
                pid = place.get("place_id")
                if pid:
                    unique_places[pid] = place  # Deduplikaatio: sama place_id ylikirjoittaa
            after = len(unique_places)
            logger.info(
                f"  Ruutu {i+1}/{len(grid_points)}: "
                f"{len(results)} tulosta, {after - before} uutta "
                f"(yhteensä {after} uniikkia)"
            )

        logger.info(
            f"Grid-haku valmis: {len(unique_places)} uniikkia yritystä, "
            f"search-kutsuja käytetty: {self._search_call_count}/{MAX_SEARCH_CALLS}"
        )
        return unique_places

    # --- Details ---

    def get_place_details(self, place_id: str) -> Dict:
        """Hakee yksittäisen paikan lisätiedot (1 detail-kutsu)."""
        fields = "name,formatted_address,formatted_phone_number,website"
        return self._make_request(
            DETAILS_URL, {"place_id": place_id, "fields": fields}, call_type="detail"
        ).get("result", {})

    def enrich_with_details(self, unique_places: Dict[str, Dict]) -> List[Dict]:
        """Hakee Details-datan max MAX_DETAIL_CALLS yritykselle rinnakkain.

        Yritykset yli rajan hylätään kokonaan — ei palauteta puutteellista dataa.
        """
        place_ids = list(unique_places.keys())[:MAX_DETAIL_CALLS]

        if len(unique_places) > MAX_DETAIL_CALLS:
            logger.warning(
                f"Uniikkeja yrityksiä {len(unique_places)}, "
                f"haetaan Details vain ensimmäiselle {MAX_DETAIL_CALLS}:lle"
            )

        enriched: List[Dict] = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self.get_place_details, pid): pid for pid in place_ids}
            for future in as_completed(futures):
                detail = future.result()
                if detail:
                    pid = futures[future]
                    base = unique_places[pid].copy()
                    base.update(detail)
                    enriched.append(base)

        logger.info(
            f"Details-haku valmis: {len(enriched)} rikastettua tulosta, "
            f"detail-kutsuja käytetty: {self._detail_call_count}/{MAX_DETAIL_CALLS}"
        )
        return enriched

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
@app.get("/search", response_model=List[GoogleSearchResult])
async def search_google(
    business_type: str = Query(..., min_length=2),
    city: str = Query(..., min_length=2)
):
    # Fast local/dev fallback so the app works even if Google API is slow or blocked
    if not USE_LIVE_GOOGLE:
        sample_results = [
            GoogleSearchResult(
                name=f"{business_type.title()} Example {i}",
                place_id=f"dev-{i}",
                address=f"Sample Street {i}, {city}",
                phone="+358 40 123 4567" if i % 2 == 0 else None,
                website=None if i % 2 == 0 else f"www.example{i}.fi",
                website_status="NO WEBSITE" if i % 2 == 0 else "BROKEN WEBSITE",
                discovery_method="DEV-MOCK",
            )
            for i in range(1, 6)
        ]
        return sample_results

    if "AIza" not in GOOGLE_API_KEY:
        raise HTTPException(500, "API Key missing")

    service = GooglePlacesService(GOOGLE_API_KEY)

    # Kaikki blokkavat Google API -kutsut ajetaan taustasäikeessä
    # jotta FastAPI:n event loop ei jäädy (time.sleep paginoinnissa)
    def _blocking_search() -> List[Dict]:
        # 1. Grid Search (geocode + nearby search + deduplikaatio)
        unique_places = service.search_grid(city, business_type)
        if not unique_places:
            return []

        # 2. Details Enrichment (rinnakkain, max MAX_DETAIL_CALLS)
        return service.enrich_with_details(unique_places)

    final_data = await asyncio.to_thread(_blocking_search)

    if not final_data:
        return []

    # 3. Website Analysis (rinnakkain, ei Google-kutsuja — ei blokkaa pitkään)
    def _blocking_website_analysis() -> List[GoogleSearchResult]:
        output = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS_WEBSITE) as ex:
            future_map = {ex.submit(analyze_website, d.get("website")): d for d in final_data}
            for f in as_completed(future_map):
                d = future_map[f]
                web_status = f.result()

                output.append(GoogleSearchResult(
                    name=d.get("name"),
                    place_id=d.get("place_id"),
                    address=d.get("formatted_address") or d.get("vicinity"),
                    phone=d.get("formatted_phone_number"),
                    website=d.get("website"),
                    website_status=web_status,
                    discovery_method="API",
                ))
        return output

    return await asyncio.to_thread(_blocking_website_analysis)

# 2. TALLENNA LIIDI (Database)
@app.post("/leads", response_model=Lead)
def create_lead(lead: LeadCreate, session: Session = Depends(get_session)):
    # Tarkista onko jo olemassa (Google Place ID:n perusteella)
    if lead.google_place_id:
        existing = session.exec(select(Lead).where(Lead.google_place_id == lead.google_place_id)).first()
        if existing:
            raise HTTPException(status_code=400, detail="Lead already exists")
            
    db_lead = Lead.model_validate(lead)
    session.add(db_lead)
    session.commit()
    session.refresh(db_lead)
    return db_lead

# 3. HAE TALLENNETUT LIIDIT (Database)
@app.get("/leads", response_model=List[Lead])
def read_leads(session: Session = Depends(get_session)):
    leads = session.exec(select(Lead).order_by(Lead.created_at.desc())).all()
    return leads

# 4. PÄIVITÄ LIIDI (Status / Notes)
@app.patch("/leads/{lead_id}", response_model=Lead)
def update_lead(lead_id: int, lead_update: LeadUpdate, session: Session = Depends(get_session)):
    db_lead = session.get(Lead, lead_id)
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
        
    lead_data = lead_update.model_dump(exclude_unset=True)
    for key, value in lead_data.items():
        setattr(db_lead, key, value)
        
    session.add(db_lead)
    session.commit()
    session.refresh(db_lead)
    return db_lead

# 5. POISTA LIIDI
@app.delete("/leads/{lead_id}")
def delete_lead(lead_id: int, session: Session = Depends(get_session)):
    db_lead = session.get(Lead, lead_id)
    if not db_lead:
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
- WEBSITE OK: sivu toimii hyvin — keskity muuhun lisäarvoon (esim. näkyvyys, päivitys)"""

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
):
    if not OPENAI_API_KEY:
        raise HTTPException(500, "OPENAI_API_KEY not configured")

    db_lead = session.get(Lead, lead_id)
    if not db_lead:
        raise HTTPException(404, "Lead not found")

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

    return EmailGenerateResponse(
        subject=subject,
        body=body,
        model=response.model,
    )