# Agency Hunter — Save State (nykytila)

## Arkkitehtuuri

```
Frontend (React 19 + TS + Vite 7)  -->  Backend (FastAPI + SQLModel)  -->  PostgreSQL (Supabase) / SQLite (dev)
         |                                         |
    Supabase Auth (JWT)  -------[Bearer token]-----+
                                                   |
                                    Google Geocoding API (kaupungin viewport)
                                    Google Places API (New) Text Search (grid search)
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
| rating | float? | Places: Google-arvosana hakuhetkellä |
| review_count | int? | Places: userRatingCount |
| business_status | str? | Places: OPERATIONAL / CLOSED_TEMPORARILY |
| primary_type | str? | Places: esim. hair_salon, barber_shop |
| maps_url | str? | Places: googleMapsUri |
| lead_score | int?, index | 0-100, lasketaan serverissä `POST /leads`:ssä (ks. Pisteytys) |
| pipeline_status | str, index | Shortlisted / Contacted / Proposal Received / Hired / Rejected |
| source | str | API / MANUAL |
| notes | str? | |
| created_at | datetime | |
| updated_at | datetime | |

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
| GET | `/search?business_type=X&city=Y` | Grid-haku Places API (New):lla (mock dev-modessa). Palauttaa `lead_score`-järjestyksessä (paras ensin), jokaisella `already_saved: bool` (onko jo käyttäjän pipelinessa) |
| POST | `/leads` | Tallenna liidi kantaan (Places-kentät mukaan, `lead_score` lasketaan serverissä) |
| GET | `/leads` | Hae kaikki tallennetut liidit |
| GET | `/leads/export?ids=1,2,3` | CSV-export valituille liideille |
| PATCH | `/leads/{lead_id}` | Päivitä status, notes, phone, website (päivittää `updated_at`) |
| DELETE | `/leads/{lead_id}` | Poista liidi |
| POST | `/leads/{lead_id}/generate-email` | AI-sähköpostiluonnos (GPT-4o-mini), tallentaa draftin kantaan |
| GET | `/leads/{lead_id}/drafts` | Hae liidin tallennetut sähköpostiluonnokset |
| GET | `/search-history` | 50 viimeisintä hakua |
| DELETE | `/search-history/{entry_id}` | Poista hakumerkintä |
| POST | `/send-email` | Lähetä sähköposti SMTP:llä |

## Tekniset valinnat

- **Google-haku (Places API New)**: Geocoding API → kaupungin viewport → 3x3 ruudukko suorakaiteita (`locationRestriction.rectangle`, ei limitystä) → `POST places.googleapis.com/v1/places:searchText` per ruutu (`textQuery`=toimiala, `pageSize` 20, `languageCode`/`regionCode` fi) → `pageToken`-sivutus max 3 sivua/ruutu (MAX_PAGES_PER_CELL) → deduplikaatio place id:llä → CLOSED_PERMANENTLY pois. Ei Details-kutsuja: kaikki kentät tulevat field maskilla suoraan hausta
- **Field mask** (`PLACES_FIELD_MASK`, `X-Goog-FieldMask`-header): places.id, displayName, formattedAddress, nationalPhoneNumber, websiteUri, rating, userRatingCount, businessStatus, primaryType, googleMapsUri + nextPageToken. Field mask määrää hinnan: rating/userRatingCount/websiteUri/nationalPhoneNumber ovat **Text Search Enterprise** -kenttiä, ja koko pyyntö laskutetaan korkeimman SKU:n mukaan
- **Hinta-arvio** (Googlen hinnasto 11/2026, 0–100k-taso): Text Search Enterprise $35 / 1000 (1000 ilmaista/kk), Geocoding $5 / 1000 (10 000 ilmaista/kk). Pahin tapaus per haku = 1 Geocoding + 14 Text Search = ~$0.50. Kauniainen-testihaku: 1 + 9 = 10 kutsua ≈ $0.32. Dokumentaatio ei kerro erikseen sivutuksen laskutusta — arvio olettaa jokaisen sivun omaksi pyynnökseen
- **Ei Places-sisällön välimuistia**: Googlen ehdot rajoittavat sisällön tallentamista; place id saa tallentaa pysyvästi. Places-kentät tallentuvat Lead-tauluun vain kun käyttäjä itse lisää liidin pipelineen
- **Turvakytkin**: MAX_SEARCH_CALLS=15 — ehdoton raja Geocoding + Text Search -kutsuille per haku. Laskuri on säieturvallinen (`threading.Lock`, varaus ennen kutsua)
- **Blokkauksen esto**: `asyncio.to_thread()` kaikille blokkaaville kutsuille (Google API, OpenAI, SMTP)
- **Rinnakkaisuus**: `ThreadPoolExecutor(max_workers=5)` website-analyysille; Google-ruudut haetaan peräkkäin (ennustettava budjetin käyttö)
- **Frontend timeout**: 60s AbortController, dynaaminen latausteksti sekuntilaskurilla
- **AI-sähköpostit**: OpenAI GPT-4o-mini, suomenkielinen system prompt, instruction-parametri iteroinnille, draftit tallentuvat kantaan
- **SMTP-lähetys**: Suora sähköpostin lähetys EmailDraftModalista, konfiguroidaan .env:ssä
- **Pipeline-navigointi**: Chevron-napit (< >) dropdownin sijaan, yhden klikkauksen stage-siirto
- **Bulk Actions**: Leijuva toolbar — Move Stage, AI Drafts, CSV Export, Delete valituille liideille (erissä, 5 kerrallaan)
- **Deep Scan**: Verkkosivun leipätekstin scraping (requests + BeautifulSoup, 5s timeout) → teksti cachetetaan Lead.website_context -kenttään → OpenAI käyttää sitä personoitujen jäänmurtajien generointiin sähköposteihin. Vikasietoinen: jos scraping epäonnistuu, meili generoidaan ilman personointia
- **Auth**: Supabase Auth + JWT. Frontend käyttää `@supabase/supabase-js`, session tallentuu selaimeen, access_token lisätään automaattisesti `apiFetch`-helperillä Authorization-headeriin. Backend verifioi JWT:n (`backend/app/auth.py`, `verify_token`-dependency) tukien sekä uusia ES256/RS256-tokeneita JWKS-endpointista (`PyJWKClient`, `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, avainten cache, macOS-venvissä certifi-SSL-context) että legacy-HS256-tokeneita `SUPABASE_JWT_SECRET`-salaisuudella. Algoritmi tunnistetaan tokenin headerista. `AUTH_DISABLED=true` ohittaa verifioinnin dev-kehityksessä. SidebarNav näyttää kirjautuneen käyttäjän emailin ja sign-out-napin
- **Multi-tenancy**: Lead, EmailDraft ja SearchHistoryEntry sisältävät `user_id`-kentän (Supabase UUID, indexed). Kaikki endpointit suodattavat `user_id == current_user.id`: GET-listat `.where(user_id)`, PATCH/DELETE/single-GET palauttavat 404:n (ei 403:a) jos toisen käyttäjän resurssia yritetään käyttää — ei paljasta resurssien olemassaoloa. POST-operaatiot asettavat `user_id` serverissä `AuthUser.id`:stä (ei clientin syötteestä). `Lead.google_place_id` ei ole enää globaalisti unique — `UniqueConstraint("google_place_id", "user_id")` sallii saman yrityksen useammalle käyttäjälle.
- **Aikaleimat**: Kaikki datetime-kentät luodaan aikavyöhykkeellisinä (`models.utc_now()` = `datetime.now(timezone.utc)`). Uudet SQLModel-versiot hylkäävät naive-datetimet. Älä käytä `datetime.utcnow()`:ia
- **Käynnistys**: FastAPI:n `lifespan`-handler kutsuu `create_db_and_tables()`, joka ajaa `create_all`:n vain dev-SQLitessä
- **Migraatiot (Alembic)**: `backend/alembic.ini` + `backend/migrations/` (`render_as_batch=True` SQLiteä varten, URL `app.database.engine`:stä eli `DATABASE_URL`:sta). Postgresissa skeema vain `alembic upgrade head`:lla. Ketju: `5c3252fb0873` alkuskeema → `a37cda0e085d` ScannedPlace pois → `ab965e378f8b` Lead Places-kentät + lead_score. `tests/test_migrations.py` ajaa upgrade + `alembic check` + downgrade/upgrade-kierroksen, joten unohtunut migraatio kaataa CI:n
- **Olemassa oleva Supabase-kanta** (luotu `create_all`:lla ennen Alembicia): aja kerran `alembic stamp 5c3252fb0873`, sitten `alembic upgrade head`, sitten `alembic check`. Huom: SQLModel 0.0.48 luo datetime-sarakkeet `timestamptz`-tyyppisinä; jos vanhat taulut on luotu `timestamp without time zone` -tyypillä, `alembic check` näyttää eron — toiminnallisesti ok (arvot ovat UTC), mutta korjaa erillisellä migraatiolla jos halutaan täysi vastaavuus
- **Riippuvuudet**: `backend/requirements.txt` lukittu tarkkoihin versioihin (`==`), testattu Python 3.13:lla puhtaassa venvissä. Päivitä versioita tietoisesti, ei automaattisesti
- **Testit**: pytest + FastAPI TestClient (`backend/tests/`, dev-riippuvuudet `backend/requirements-dev.txt`). `conftest.py` asettaa env-muuttujat ennen app-importtia (ei `backend/.env`:n oikeita avaimia/kantaa), käyttää in-memory SQLiteä (StaticPool) ja `dependency_overrides`-mekanismia `get_session`- ja `verify_token`-dependencyille. Käyttäjä valitaan `X-Test-User`-headerilla (`client_a` / `client_b` -fixturet) tenant-isolaation testaamiseen. Autouse-fixture estää oikeat kutsut (requests, OpenAI, scraping, SMTP); testit mockaavat tarvitsemansa
- **CI**: GitHub Actions (`.github/workflows/ci.yml`) push- ja pull_request-eventeillä: backend (Python 3.13, pytest) ja frontend (Node 22, `npm ci` + lint + build). Ei API-avaimia
- **UI hakutuloksille**: LeadTable — score-badge (75+ vihreä, 50+ lime, 25+ keltainen, muuten harmaa), rating + arvostelumäärä, Google Maps -linkki, "Temporarily closed" -merkintä, "In pipeline" jo tallennetuille (Save-nappi piilossa). Oletusjärjestys score desc, sarakkeet Score/Business/Rating/Status klikattavia. PipelineCard näyttää scoren ja ratingin
- **Tietokanta**: Dev SQLite, tuotanto PostgreSQL (Supabase). `DATABASE_URL` tukee `postgres://`- ja `postgresql://`-muotoja, Postgresissa pool_pre_ping + pool_size=5

## Pisteytys (lead_score)

`backend/app/scoring.py`, puhdas funktio `lead_score(website_status, rating, review_count, business_status) -> int` (0–100). Periaate: paras liidi on toimiva, suosittu yritys jolla on huono tai puuttuva nettisivu. Kaikki painot ovat moduulin vakioita — säädä niitä ja aja `pytest tests/test_scoring.py`.

```
jos business_status == CLOSED_PERMANENTLY:  score = 0
reviews = review_count tai 0   (Google jättää kentän pois kun arvosteluja ei ole)

score  = WEBSITE_POINTS[website_status]                         NO WEBSITE 55 | BROKEN 50 | NOT MOBILE 35 | OK 5 | tuntematon 0
jos reviews == 0:
    score -= NO_REVIEWS_PENALTY                                 5
muuten:
    score += REVIEW_MAX_POINTS * min(1, ln(1+reviews) / ln(1+REVIEW_SATURATION))          max 30, täysi 200 arvostelusta
    score += RATING_MAX_POINTS * clamp((rating - 3.0) / 2.0) * min(1, reviews / 10)       max 15; <=3.0 -> 0; luottamus täysi 10 arvostelusta
jos business_status == CLOSED_TEMPORARILY:
    score -= CLOSED_TEMPORARILY_PENALTY                         40
score = clamp(round(score), 0, 100)
```

| Vakio | Arvo | Vaikutus |
|---|---|---|
| WEBSITE_POINTS | 55 / 50 / 35 / 5 | Nettisivun tila, painavin tekijä |
| REVIEW_MAX_POINTS / REVIEW_SATURATION | 30 / 200 | Aktiivisuus (log-asteikko) |
| RATING_MAX_POINTS, RATING_FLOOR, RATING_CEIL | 15, 3.0, 5.0 | Laatu |
| RATING_CONFIDENCE_REVIEWS | 10 | 5.0/1 arvostelu ei saa täysiä pisteitä |
| NO_REVIEWS_PENALTY | 5 | Ei arvosteluja: kuollut tai uusi |
| CLOSED_TEMPORARILY_PENALTY | 40 | Tilapäisesti suljettu |

Esimerkkejä: NO WEBSITE + 4.6/120 → 94; BROKEN + 4.6/11 → 76; NO WEBSITE ilman arvosteluja → 50; WEBSITE OK + 4.9/340 → 49; WEBSITE OK ilman arvosteluja → 0.

Pisteet lasketaan `/search`-vastaukseen jokaiselle tulokselle ja `POST /leads`:ssä tallennettavalle liidille (clientin lähettämä arvo ohitetaan). Vanhoilla, ennen Phase 12a:ta tallennetuilla liideillä `lead_score` on NULL.

## Ympäristömuuttujat (backend/.env)

Pohja: `backend/.env.example` (versionhallinnassa, `.gitignore`:ssa poikkeus `!.env.example`).

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

Pohja: `.env.example` repon juuressa.

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
backend/app/models.py          — Lead, LeadCreate, LeadUpdate, SearchHistoryEntry, EmailDraft
backend/app/scoring.py         — lead_score(): liidin pisteytys 0-100, painot vakioina
backend/alembic.ini, backend/migrations/ — Alembic-migraatiot (versions/)
backend/app/database.py        — DB-yhteys (SQLite dev, Postgres tuotannossa)
backend/app/auth.py            — Supabase JWT -verifiointi (ES256/RS256 JWKS + HS256 legacy, verify_token FastAPI-dependency)
backend/app/utils/scraper.py   — Deep Scan: verkkosivun leipätekstin scraping (5s timeout, max 2000 merkkiä)
backend/tests/conftest.py      — Testifixturet: in-memory SQLite, auth-override (client_a/client_b), verkkoesto
backend/tests/test_*.py        — Leads CRUD, tenant-isolaatio, haku + AI-email, Places API (field mask, sivutus, kutsuraja), pisteytys, migraatiot
.github/workflows/ci.yml       — CI: pytest + npm lint + build
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
src/components/LeadTable.tsx    — Hakutulosten taulukko (järjestettävät sarakkeet, score, rating, Maps, In pipeline)
src/components/ScoreBadge.tsx   — ScoreBadge + RatingDisplay (LeadTable ja PipelineCard)
src/types/agency.ts            — SearchResult, Agency, SavedAgency, PipelineStatus, BusinessStatus, NavTab
```
