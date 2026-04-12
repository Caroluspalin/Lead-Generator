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
- **react-icons** (SidebarNav) + **lucide-react** (muu UI) — kaksi ikonikirjastoa
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

- Nosta paginointi 2 → 3 sivuun (Google max 60 tulosta per haku)
- Toteuta grid search: jaa kaupunki osiin `get_city_bounds` + `NEARBY_SEARCH_URL` -yhdistelmalla, hae jokaisesta ruudusta erikseen ja yhdista tulokset (deduplikointi place_id:lla)
- Tavoite: loyda kaikki yritykset, ei vain Googlen "relevantimmat"
