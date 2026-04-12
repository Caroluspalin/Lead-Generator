# FILE: backend/app/main.py
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

# Safety Limits
MAX_RESULTS_SAFETY = 60
GRID_RADIUS_METERS = 2000
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

    def _make_request(self, url: str, params: Dict) -> Dict:
        params["key"] = self.key
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"API Error: {e}")
            return {}

    def get_city_bounds(self, city_name: str) -> Optional[Dict]:
        data = self._make_request(GEOCODE_URL, {"address": f"{city_name}, Finland"})
        if not data.get("results"): return None
        return data["results"][0]["geometry"].get("viewport")

    def search_place_pagination(self, url: str, params: Dict) -> List[Dict]:
        all_res = []
        next_token = None
        for _ in range(2): # Max 2 sivua per haku (säästöä)
            if next_token:
                params["pagetoken"] = next_token
                time.sleep(2)
            data = self._make_request(url, params)
            all_res.extend(data.get("results", []))
            next_token = data.get("next_page_token")
            if not next_token: break
        return all_res

    def get_place_details(self, place_id: str) -> Dict:
        fields = "name,formatted_address,formatted_phone_number,website"
        return self._make_request(DETAILS_URL, {"place_id": place_id, "fields": fields}).get("result", {})

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
    
    # 1. Text Search
    results = service.search_place_pagination(TEXT_SEARCH_URL, {"query": f"{business_type} in {city}"})
    unique_places = {p["place_id"]: p for p in results}

    # 2. Details Enrichment (Parallel)
    final_data = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(service.get_place_details, pid): pid for pid in unique_places}
        for f in as_completed(futures):
            res = f.result()
            if res:
                # Yhdistä alkuperäinen ja detail-data
                pid = futures[f]
                base = unique_places[pid]
                base.update(res)
                final_data.append(base)

    # 3. Website Analysis & Formatting
    output = []
    with ThreadPoolExecutor(max_workers=5) as ex:
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
                discovery_method="API"
            ))

    return output

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