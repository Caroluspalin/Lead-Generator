# Agency Hunter - Projektin konteksti

## Tavoite (MVP)

Liidigeneraattori paikallisille yrityksille. Ydinlooppi:

1. **Haku** — Kayttaja syottaa toimialan + kaupungin -> Google Places API palauttaa yritykset
2. **Nettisivuanalyysi** — Jokaisen yrityksen nettisivun tila tarkistetaan automaattisesti (viewport meta-tag -tarkistus mukaan lukien)
3. **Tallennus** — Kayttaja tallentaa kiinnostavat liidit tietokantaan (SQLite)
4. **Hallinta** — Tallennettujen liidien pipeline-statusta ja muistiinpanoja voi muokata

## Teknologiapino

### Frontend
- **React 19** + TypeScript + Vite 7
- **Tailwind CSS 3** (PostCSS)
- **framer-motion** (animaatiot)
- **lucide-react** (ikonit, yhtenaistetty Phase 4:ssa)
- **sonner** (toast-ilmoitukset)
- Ei routeria — navigaatio hoidetaan `activeTab`-tilalla (search | pipeline | comparison | guides)

### Backend
- **FastAPI** (Python)
- **SQLModel** (ORM, Pydantic + SQLAlchemy)
- **SQLite** (kehityksessa, DATABASE_URL .env:ssa — vaihdettavissa PostgreSQL:iin)
- **Google Places API** (Text Search + Details + Geocode)
- **requests** + **BeautifulSoup4** (nettisivuanalyysi + viewport-tarkistus)

### Infra
- `docker-compose.yml` olemassa PostgreSQL + pgAdmin -kayttoon (ei pakollinen kehityksessa)
- Backend: `uvicorn app.main:app --reload` (backend/-kansiosta)
- Frontend: `npm run dev` (projektin juuresta)

## Tietomalli

### Backend: Lead (tietokantataulu — backend/app/models.py)
```
id              - int, PK, auto
google_place_id - str?, unique, index (duplikaattien esto)
name            - str
city            - str, index
address         - str?
phone           - str?
website         - str?
website_status  - str? (NO WEBSITE | BROKEN WEBSITE | NOT MOBILE | WEBSITE OK)
pipeline_status - str (Shortlisted | Contacted | Proposal Received | Hired | Rejected), index
source          - str (API | MANUAL)
notes           - str?
created_at      - datetime
updated_at      - datetime
```

### Frontend: Agency (hakutulos — src/types/agency.ts)
```
id               - string (= Google place_id)
name             - string
city             - string
address          - string
phone?           - string
website?         - string
website_status   - string
discovery_method - string
```

### Frontend: SavedAgency (tallennettu liidi, vastaa backendin Lead-mallia)
```
id              - number (backendin auto-id)
google_place_id - string?
name            - string
city            - string
address?        - string
phone?          - string
website?        - string
website_status? - string
pipeline_status - PipelineStatus
source          - string
notes?          - string
created_at      - string
updated_at      - string
```

## Statukset

### Pipeline-statukset (liidin myyntivaihe)
`Shortlisted` -> `Contacted` -> `Proposal Received` -> `Hired` | `Rejected`

### Nettisivu-statukset (tekninen analyysi)
| Status | Vari | Merkitys |
|---|---|---|
| `NO WEBSITE` | Punainen | Yrityksella ei ole nettisivua |
| `BROKEN WEBSITE` | Oranssi | Sivu palauttaa HTTP-virheen tai ei vastaa |
| `NOT MOBILE` | Keltainen | Sivu toimii mutta puuttuu viewport meta-tag |
| `WEBSITE OK` | Vihrea | Sivu toimii ja on mobiiliystävallinen |

"Myyntipaikat"-filtteri piilottaa `WEBSITE OK` -tulokset (ne eivat ole potentiaalisia asiakkaita).

## API-endpointit

| Metodi | Polku | Tarkoitus |
|---|---|---|
| GET | `/search?business_type=X&city=Y` | Google Places -haku (stateless, mock-fallback dev-modessa) |
| POST | `/leads` | Tallenna liidi kantaan (LeadCreate) |
| GET | `/leads` | Hae kaikki tallennetut liidit (jarjestetty created_at desc) |
| PATCH | `/leads/{lead_id}` | Paivita pipeline_status, notes, phone tai website (LeadUpdate) |
| DELETE | `/leads/{lead_id}` | Poista liidi |

## Ymparistomuuttujat (backend/.env)

```
DATABASE_URL=sqlite:///agency_hunter.db    # tai postgresql://...
GOOGLE_API_KEY=AIza...                     # Google Places API
USE_LIVE_GOOGLE=false                      # true = oikea API, false = mock-data
```

## Komennot

```bash
# Frontend (projektin juuresta)
npm run dev

# Backend (backend/-kansiosta, venv aktiivisena)
cd backend
source venv/bin/activate
uvicorn app.main:app --reload

# Tietokanta (valinnainen, vain jos kayttaa PostgreSQL:ia)
docker compose up -d
```

## Arkkitehtuuri: Frontendin ja backendin yhteys

`PipelineContext` (src/context/PipelineContext.tsx) hoitaa kaiken kommunikaation backendiin:
- `addToPipeline(agency)` -> `POST /leads`
- `refresh()` / mount -> `GET /leads`
- `updateStatus(id, status)` -> `PATCH /leads/{id}`
- `updateNotes(id, notes)` -> `PATCH /leads/{id}`
- `removeFromPipeline(id)` -> `DELETE /leads/{id}`

Kaikki data persistoidaan tietokantaan. Frontendin tila synkronoidaan backendin vastausten perusteella.

## Kieli

UI-kieli: **englanti**. Kaikki napit, otsikot, placeholder-tekstit ja ilmoitukset englanniksi (Phase 4:ssa yhdenmukaistettu).

## Phase 5: Hakualgoritmin laajennus (TODO)

Tavoite: loyda kaikki toimialan yritykset kaupungista, ei vain Googlen "relevantimmat".
Muutettava tiedosto: **backend/app/main.py** (frontend ei muutu).

### 1. Grid Search -logiikka

Nykyinen: yksi Text Search -kutsu → max 40 tulosta.
Uusi: jaa kaupunki ruudukkoon, hae jokaisesta ruudusta erikseen.

```
Vaihe 1: Geocode-kutsu → get_city_bounds(city) → viewport (northeast, southwest)
Vaihe 2: Jaa viewport 2x2 ruudukkoon → 4 ruutua, laske jokaisen keskipiste (lat, lng)
Vaihe 3: Jokaiselle ruudulle Nearby Search:
         location=lat,lng & radius=GRID_RADIUS_METERS(2000) & keyword=business_type
Vaihe 4: Yhdista kaikki tulokset yhteen dict:iin {place_id: data} → automaattinen deduplikaatio
```

Deduplikaatio: sama `place_id` eri ruuduista ylikirjoittaa itsensa dict:issa.
Ruudukon koko: 2x2 = 4 ruutua (konservatiivinen alku, riittaa Tampere-kokoisille kaupungeille).

### 2. Paginoinnin nosto ja viive

Nosta `search_place_pagination` max-sivut: 2 → 3 (Googlen max, 60 tulosta per ruutu).
Google vaatii ~2s viiveen next_page_token:n kayton valilla — nykyinen `time.sleep(2)` sailyy.
Blokkaus: kaytetaan `asyncio.to_thread()` wrapperia jotta FastAPI event loop ei blokkaudu.

### 3. Turvakytkin: KAKSI erillistä hard-limitia

```python
class GooglePlacesService:
    MAX_SEARCH_CALLS = 15   # Geocode + Nearby Search + paginointi yhteensa
    MAX_DETAIL_CALLS = 40   # Place Details -kutsut (1 per uniikki yritys)

    def __init__(self, api_key):
        self.key = api_key
        self._search_call_count = 0
        self._detail_call_count = 0
```

**MAX_SEARCH_CALLS = 15:** Kattaa kaiken hakuvaiheen (1 geocode + max 4 ruutua x 3 sivua = 13, yhteensa 14). Jos limitti tulee vastaan, haku palauttaa mita ehti loyda.

**MAX_DETAIL_CALLS = 40:** Jos uniikkeja yrityksia loytyy ruudukkohausta 100+, Details-data haetaan vain ensimmaiselle 40:lle. Loput hylataan kokonaan — niita EI palauteta frontendille ilman Details-dataa, koska puutteelliset tulokset olisivat harhaanjohtavia.

Molemmat limitit toimivat samalla periaatteella: `_make_request` tarkistaa laskurin, rajan ylittyessa palauttaa tyhjan `{}` ja logittaa varoituksen.

### 4. Kutsulaskuri pahimmassa tapauksessa

| Vaihe | Kutsut | Limitti |
|---|---|---|
| Geocode (kaupungin rajat) | 1 | MAX_SEARCH_CALLS (15) |
| 4 ruutua x max 3 sivua Nearby Search | 4-12 | MAX_SEARCH_CALLS (15) |
| Details (per uniikki yritys, max 40) | 1-40 | MAX_DETAIL_CALLS (40) |
| Website-analyysi (requests, ei Google) | 1-40 | Ei Google-kutsuja |
| **Pahimman tapauksen Google-kutsut** | **53** | **Rajattu 15+40=55** |

### 5. Muutokset main.py:ssa

- `GooglePlacesService`: lisaa `_search_call_count`, `_detail_call_count`, limitit
- `_make_request`: lisaa laskuri + tarkistus (erillinen search/detail-parametri)
- Uusi metodi `generate_grid_points(viewport, grid_size=2)`: palauttaa keskipisteet
- `search_place_pagination`: max-sivut 2 → 3
- `search_google` endpoint: text search → grid-based nearby search + `asyncio.to_thread()`
- Details-kutsut: leikkaa uniikkien listan `[:MAX_DETAIL_CALLS]` ennen ThreadPoolExecutoria
- Frontend ei muutu — API-vastaus on taysmalleen samaa `List[GoogleSearchResult]` -muotoa
