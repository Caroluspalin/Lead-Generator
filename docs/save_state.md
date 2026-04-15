# Agency Hunter — Save State (nykytila)

## Arkkitehtuuri

```
Frontend (React 19 + TS + Vite 7)  -->  Backend (FastAPI + SQLModel)  -->  PostgreSQL (Supabase) / SQLite (dev)
         |                                         |
    Supabase Auth (JWT)  -------[Bearer token]-----+
                                                   |
                                    Google Places API (grid search)
                                    OpenAI API (email drafts)
                                    SMTP (email sending)
```

- Frontend: `npm run dev` (localhost:5173)
- Backend: `uvicorn app.main:app --reload` (127.0.0.1:8000)
- Ei routeria — navigaatio `activeTab`-tilalla (search | pipeline | dashboard | history)
- Kirjautumaton käyttäjä näkee Login-komponentin; kirjautumisen jälkeen AppShell renderöityy normaalisti

## Tietokanta

### Lead

| Kentta | Tyyppi | Huom |
|---|---|---|
| id | int, PK, auto | |
| user_id | str, index | Supabase user UUID — omistaja |
| google_place_id | str?, index | Duplikaattien esto (unique per user_id, ks. UniqueConstraint) |
| name | str | |
| city | str, index | |
| address | str? | |
| phone | str? | |
| website | str? | |
| website_status | str? | NO WEBSITE / BROKEN WEBSITE / NOT MOBILE / WEBSITE OK |
| website_context | str? | Deep Scan: skraapattu verkkosivun leipäteksti (max 2000 merkkiä) |
| scraped_at | datetime? | Deep Scan: milloin verkkosivun teksti haettiin |
| pipeline_status | str, index | Shortlisted / Contacted / Proposal Received / Hired / Rejected |
| source | str | API / MANUAL |
| notes | str? | |
| created_at | datetime | |
| updated_at | datetime | |

### ScannedPlace

| Kentta | Tyyppi | Huom |
|---|---|---|
| id | int, PK, auto | |
| google_place_id | str, unique, index | Jo Details-haulla käsitelty yritys |
| scanned_at | datetime | UTC-aikaleima |

Globaali cache (ei user_id:tä): place_id on julkista Google-dataa ja per-user cache kaksinkertaistaisi API-laskun. Jos halutaan "vain minun skannaukseni" -tilasto → erillinen UserSearchLog-taulu, ei puututa cache-tauluun.

### SearchHistoryEntry

| Kentta | Tyyppi | Huom |
|---|---|---|
| id | int, PK, auto | |
| user_id | str, index | Supabase user UUID — omistaja |
| business_type | str | Hakusana |
| city | str | Kaupunki |
| result_count | int | Tulosten määrä |
| searched_at | datetime | UTC-aikaleima |

### EmailDraft

| Kentta | Tyyppi | Huom |
|---|---|---|
| id | int, PK, auto | |
| user_id | str, index | Supabase user UUID — omistaja |
| lead_id | int, index | Viittaus Lead-tauluun |
| subject | str | Sähköpostin otsikko |
| body | str | Sähköpostin teksti |
| model | str | Käytetty AI-malli |
| created_at | datetime | UTC-aikaleima |

## API-endpointit

| Metodi | Polku | Tarkoitus |
|---|---|---|
| GET | `/search?business_type=X&city=Y` | Grid-haku Google Places API:lla (mock-fallback dev-modessa) |
| POST | `/leads` | Tallenna liidi kantaan |
| GET | `/leads` | Hae kaikki tallennetut liidit |
| GET | `/leads/export?ids=1,2,3` | CSV-export valituille liideille |
| PATCH | `/leads/{lead_id}` | Päivitä status, notes, phone, website |
| DELETE | `/leads/{lead_id}` | Poista liidi |
| POST | `/leads/{lead_id}/generate-email` | AI-sähköpostiluonnos (GPT-4o-mini), tallentaa draftin kantaan |
| GET | `/leads/{lead_id}/drafts` | Hae liidin tallennetut sähköpostiluonnokset |
| GET | `/search-history` | 50 viimeisintä hakua |
| DELETE | `/search-history/{entry_id}` | Poista hakumerkintä |
| POST | `/send-email` | Lähetä sähköposti SMTP:llä |

## Tekniset valinnat

- **Grid Search**: 3x3 ruudukko, dynaaminen säde viewportista, 20% limittyminen (GRID_OVERLAP_FACTOR=1.2)
- **Turvakytkimet**: MAX_SEARCH_CALLS=15, MAX_DETAIL_CALLS=40 — ehdottomat Google API -rajat
- **Blokkauksen esto**: `asyncio.to_thread()` kaikille blokkaaville kutsuille (Google API, OpenAI, SMTP, time.sleep)
- **Rinnakkaisuus**: `ThreadPoolExecutor(max_workers=5)` Details- ja website-analyyseille
- **Frontend timeout**: 60s AbortController, dynaaminen latausteksti sekuntilaskurilla
- **AI-sähköpostit**: OpenAI GPT-4o-mini, suomenkielinen system prompt, instruction-parametri iteroinnille, draftit tallentuvat kantaan
- **SMTP-lähetys**: Suora sähköpostin lähetys EmailDraftModalista, konfiguroidaan .env:ssä
- **ScannedPlace-cache**: Jo skannatut place_id:t tallennetaan kantaan — toistuvat haut eivät kuluta Details API -kutsuja
- **Pipeline-navigointi**: Chevron-napit (< >) dropdownin sijaan, yhden klikkauksen stage-siirto
- **Bulk Actions**: Leijuva toolbar — Move Stage, AI Drafts, CSV Export, Delete valituille liideille (erissä, 5 kerrallaan)
- **Deep Scan**: Verkkosivun leipätekstin scraping (requests + BeautifulSoup, 5s timeout) → teksti cachetetaan Lead.website_context -kenttään → OpenAI käyttää sitä personoitujen jäänmurtajien generointiin sähköposteihin. Vikasietoinen: jos scraping epäonnistuu, meili generoidaan ilman personointia
- **Auth**: Supabase Auth + JWT. Frontend käyttää `@supabase/supabase-js`, session tallentuu selaimeen, access_token lisätään automaattisesti `apiFetch`-helperillä Authorization-headeriin. Backend verifioi JWT:n (`backend/app/auth.py`, `verify_token`-dependency) tukien sekä uusia ES256/RS256-tokeneita JWKS-endpointista (`PyJWKClient`, `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, avainten cache, macOS-venvissä certifi-SSL-context) että legacy-HS256-tokeneita `SUPABASE_JWT_SECRET`-salaisuudella. Algoritmi tunnistetaan tokenin headerista. `AUTH_DISABLED=true` ohittaa verifioinnin dev-kehityksessä. SidebarNav näyttää kirjautuneen käyttäjän emailin ja sign-out-napin
- **Multi-tenancy**: Lead, EmailDraft ja SearchHistoryEntry sisältävät `user_id`-kentän (Supabase UUID, indexed). Kaikki endpointit suodattavat `user_id == current_user.id`: GET-listat `.where(user_id)`, PATCH/DELETE/single-GET palauttavat 404:n (ei 403:a) jos toisen käyttäjän resurssia yritetään käyttää — ei paljasta resurssien olemassaoloa. POST-operaatiot asettavat `user_id` serverissä `AuthUser.id`:stä (ei clientin syötteestä). `Lead.google_place_id` ei ole enää globaalisti unique — `UniqueConstraint("google_place_id", "user_id")` sallii saman yrityksen useammalle käyttäjälle. ScannedPlace pysyy globaalina cachena (ei user_id:tä, ks. tietokantaosio)
- **Tietokanta**: Dev SQLite, tuotanto PostgreSQL (Supabase). `DATABASE_URL` tukee `postgres://`- ja `postgresql://`-muotoja, Postgresissa pool_pre_ping + pool_size=5

## Ympäristömuuttujat (backend/.env)

```
DATABASE_URL=sqlite:///agency_hunter.db   # tai postgresql://... Supabasesta
SQL_ECHO=false
SUPABASE_URL=https://<project>.supabase.co   # pakollinen ES256/RS256-tokeneille (JWKS)
SUPABASE_JWT_SECRET=                         # pakollinen HS256-legacy-tokeneille
SUPABASE_JWT_AUDIENCE=authenticated
AUTH_DISABLED=false        # dev-override, ohittaa JWT-verifioinnin
ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
GOOGLE_API_KEY=...
USE_LIVE_GOOGLE=false
OPENAI_API_KEY=...
SMTP_HOST=         # esim. smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
```

## Ympäristömuuttujat (frontend .env.local)

```
VITE_API_BASE=http://127.0.0.1:8000
VITE_SUPABASE_URL=https://<project>.supabase.co
VITE_SUPABASE_ANON_KEY=
```

## Frontend-kirjastot

React 19, Tailwind CSS 3, framer-motion, lucide-react, sonner

## Tiedostorakenne (avaintiedostot)

```
backend/app/main.py            — GooglePlacesService, email/SMTP service, kaikki endpointit
backend/app/models.py          — Lead, LeadCreate, LeadUpdate, ScannedPlace, SearchHistoryEntry, EmailDraft
backend/app/database.py        — DB-yhteys (SQLite dev, Postgres tuotannossa)
backend/app/auth.py            — Supabase JWT -verifiointi (ES256/RS256 JWKS + HS256 legacy, verify_token FastAPI-dependency)
backend/app/utils/scraper.py   — Deep Scan: verkkosivun leipätekstin scraping (5s timeout, max 2000 merkkiä)
src/lib/supabaseClient.ts      — Supabase-client (VITE_SUPABASE_URL + ANON_KEY)
src/lib/api.ts                 — apiFetch: lisää Authorization-Bearer-tokenin kaikkiin pyyntöihin
src/context/AuthContext.tsx    — Sessionin hallinta (signIn/signUp/signOut)
src/components/Login.tsx       — Kirjautumis- ja rekisteröitymis-lomake
src/App.tsx                    — Haku-UI, tab-navigaatio (search | pipeline | dashboard | history)
src/context/PipelineContext.tsx — Globaali tila + API-kutsut backendiin
src/components/PipelineCard.tsx — Liidikortti (checkbox, chevron-navigointi, notes, AI Draft)
src/components/PipelineBoard.tsx — Pipeline-kanban + Bulk Actions -toolbar
src/components/EmailDraftModal.tsx — AI-sähköpostimodaali + SMTP Send -nappi
src/components/DashboardView.tsx — Dashboard-analytiikka (KPI, funnel, website status)
src/components/SearchHistoryView.tsx — Hakuhistoria + re-search
src/components/AddBusinessModal.tsx — Manuaalinen liidin lisäys
src/components/SidebarNav.tsx   — Sivupalkki-navigaatio
src/components/LeadTable.tsx    — Hakutulosten taulukko
src/components/Navbar.tsx       — NavTab-tyypit (ei käytössä, SidebarNav korvaa)
src/types/agency.ts            — Agency, SavedAgency, PipelineStatus
```
