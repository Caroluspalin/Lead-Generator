# Agency Hunter — Save State (nykytila)

## Arkkitehtuuri

```
Frontend (React 19 + TS + Vite 7)  -->  Backend (FastAPI + SQLModel)  -->  SQLite
                                                |
                                    Google Places API (grid search)
                                    OpenAI API (email drafts)
```

- Frontend: `npm run dev` (localhost:5173)
- Backend: `uvicorn app.main:app --reload` (127.0.0.1:8000)
- Ei routeria — navigaatio `activeTab`-tilalla (search | pipeline)

## Tietokanta: Lead-taulu

| Kentta | Tyyppi | Huom |
|---|---|---|
| id | int, PK, auto | |
| google_place_id | str?, unique, index | Duplikaattien esto |
| name | str | |
| city | str, index | |
| address | str? | |
| phone | str? | |
| website | str? | |
| website_status | str? | NO WEBSITE / BROKEN WEBSITE / NOT MOBILE / WEBSITE OK |
| pipeline_status | str, index | Shortlisted / Contacted / Proposal Received / Hired / Rejected |
| source | str | API / MANUAL |
| notes | str? | |
| created_at | datetime | |
| updated_at | datetime | |

## Tietokanta: ScannedPlace-taulu

| Kentta | Tyyppi | Huom |
|---|---|---|
| id | int, PK, auto | |
| google_place_id | str, unique, index | Jo Details-haulla käsitelty yritys |
| scanned_at | datetime | UTC-aikaleima |

## API-endpointit

| Metodi | Polku | Tarkoitus |
|---|---|---|
| GET | `/search?business_type=X&city=Y` | Grid-haku Google Places API:lla (mock-fallback dev-modessa) |
| POST | `/leads` | Tallenna liidi kantaan |
| GET | `/leads` | Hae kaikki tallennetut liidit |
| PATCH | `/leads/{lead_id}` | Paivita status, notes, phone, website |
| DELETE | `/leads/{lead_id}` | Poista liidi |
| POST | `/leads/{lead_id}/generate-email` | AI-sahkopostiluonnos (GPT-4o-mini) |

## Tekniset valinnat

- **Grid Search**: 3x3 ruudukko, dynaaminen sade viewportista, 20% limittyminen (GRID_OVERLAP_FACTOR=1.2)
- **Turvakytkimet**: MAX_SEARCH_CALLS=15, MAX_DETAIL_CALLS=40 — ehdottomat Google API -rajat
- **Blokkauksen esto**: `asyncio.to_thread()` kaikille blokkaaville kutsuille (Google API, OpenAI, time.sleep)
- **Rinnakkaisuus**: `ThreadPoolExecutor(max_workers=5)` Details- ja website-analyyseille
- **Frontend timeout**: 60s AbortController, dynaaminen latausteksti sekuntilaskurilla
- **AI-sahkopostit**: OpenAI GPT-4o-mini, suomenkielinen system prompt, instruction-parametri iteroinnille
- **ScannedPlace-cache**: Jo skannatut place_id:t tallennetaan kantaan — toistuvat haut eivät kuluta Details API -kutsuja samoihin yrityksiin
- **Pipeline-navigointi**: Chevron-napit (< >) dropdownin sijaan, yhden klikkauksen stage-siirto

## Ymparistomuuttujat (backend/.env)

```
DATABASE_URL=sqlite:///agency_hunter.db
GOOGLE_API_KEY=...
USE_LIVE_GOOGLE=false
OPENAI_API_KEY=...
```

## Frontend-kirjastot

React 19, Tailwind CSS 3, framer-motion, lucide-react, sonner

## Tiedostorakenne (avaintiedostot)

```
backend/app/main.py          — GooglePlacesService, email service, kaikki endpointit
backend/app/models.py        — Lead, LeadCreate, LeadUpdate, ScannedPlace
backend/app/database.py      — DB-yhteys
src/App.tsx                   — Haku-UI, tab-navigaatio
src/context/PipelineContext.tsx — Globaali tila + API-kutsut backendiin
src/components/PipelineCard.tsx — Liidikortti (chevron-navigointi, notes, AI Draft -nappi)
src/components/EmailDraftModal.tsx — AI-sahkopostimodaali
src/components/PipelineBoard.tsx — Pipeline-kanban
src/types/agency.ts           — Agency, SavedAgency, PipelineStatus
```
