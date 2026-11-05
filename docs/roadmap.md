# Agency Hunter — Roadmap

## Tehty

- **Phase 1-3**: Perus-MVP — FastAPI + React, Google Text Search, Lead CRUD, pipeline-hallinta
- **Phase 4**: UI-yhtenäistäminen — lucide-react, englanninkielinen UI, Tailwind-pohjaiset komponentit
- **Phase 5**: Hakualgoritmin laajennus — 3x3 grid search, dynaaminen säde, turvakytkimet (15+40), asyncio.to_thread, 60s frontend timeout
- **Phase 6**: AI-sähköpostiavustaja — OpenAI GPT-4o-mini, POST /leads/{id}/generate-email, EmailDraftModal, instruction-parametri iteroinnille, copy to clipboard
- **Phase 7**: ScannedPlace Caching — `ScannedPlace`-taulu, Details API -kutsujen deduplikaatio tietokantapohjaisella cachella
- **Phase 8**: UX ja Workflow-optimointi:
  - Pipeline chevron-navigointi (< >) dropdownin sijaan
  - Bulk Actions -toolbar (Move Stage, AI Drafts, CSV Export, Delete)
  - Dashboard-analytiikka (KPI-kortit, pipeline funnel, website status breakdown)
  - Search History (tallennus kantaan, re-search, poisto)
  - Email Draft -persistenssi (draftit tallentuvat EmailDraft-tauluun)
  - SMTP-sähköpostin lähetys suoraan EmailDraftModalista
  - AddBusinessModal scrollaus-korjaus
- **Phase 9**: AI Deep Scan — verkkosivun scraping (requests+BS4, 5s timeout), tekstin caching Lead-tauluun (website_context), OpenAI-prompti laajennettu personoiduilla jäänmurtajilla, vikasietoinen fallback
- **Phase 10**: Tuotantovalmius:
  - PostgreSQL-tuki (Supabase) `database.py`:ssä, `postgres://` → `postgresql://` -normalisointi, pool_pre_ping
  - Supabase Auth + JWT-verifiointi backendissä (`backend/app/auth.py`, PyJWT[crypto] + certifi): uudet ES256/RS256-tokenit JWKS-endpointista (PyJWKClient, avainten cache) sekä legacy-HS256-tokenit symmetrisellä secretillä
  - Sidebar sign-out -nappi + kirjautuneen käyttäjän email
  - Kaikki kirjoittavat + liidien luku/draftit/history-endpointit suojattu `verify_token`-dependencyllä
  - Frontend: `@supabase/supabase-js`, `AuthContext`, `Login`-komponentti, `apiFetch`-helper JWT-injektioon
  - CORS rajoitettu `ALLOWED_ORIGINS`-env-muuttujalla
  - `.env.example`-tiedostot sekä backendille että frontendille
- **Phase 11a**: Multi-tenancy (sovellustaso):
  - `user_id`-kenttä (str, indexed) malleihin: `Lead`, `EmailDraft`, `SearchHistoryEntry`
  - `Lead.google_place_id` ei enää globaalisti unique — `UniqueConstraint("google_place_id", "user_id")` sallii saman yrityksen useammalle käyttäjälle
  - Kaikki endpointit suodattavat/tarkistavat `user_id == current_user.id` — 404 (ei 403) toisen käyttäjän resurssista
  - POST-operaatiot asettavat `user_id` serverissä (`AuthUser.id`), ei clientin syötteestä
  - ScannedPlace pysyy globaalina cachena (julkinen place_id, per-user cache kaksinkertaistaisi API-laskun)
  - Dev-SQLite poistettu schema-muutosten takia (CLAUDE.md:n ohjeen mukaan, ei Alembicia)
- **Phase 11c**: Korjaukset ja riippuvuuksien lukitus:
  - `backend/requirements.txt` lukittu tarkkoihin versioihin (`==`), mukana myös SQLAlchemy, pydantic ja starlette
  - `datetime.utcnow()` → `datetime.now(timezone.utc)` (`models.utc_now()`): korjaa 500-virheen "Datetime values must have timezone information" uusimmalla SQLModelilla
  - `@app.on_event("startup")` → `lifespan`-handler
  - `lucide-react` lisätty `package.json`:iin (puuttui, vaikka käytössä kaikkialla)
  - TypeScript-buildikorjaukset: `SidebarNav`-togglen tyyppi (`React.Dispatch<React.SetStateAction<boolean>>`), `import type { ReactNode }` konteksteissa, käyttämätön `Globe`-import, Retry-napin `onClick` (välitti MouseEventin hakusanaksi)
  - `NavTab`-tyyppi siirretty `src/types/agency.ts`:ään, käyttämätön `Navbar.tsx` poistettu
  - ESLint: `react-refresh/only-export-components` ohitettu rivikohtaisesti `useAuth`/`usePipeline`-hookeille
  - `.gitignore`: `!.env.example` → `.env.example`-tiedostot ovat nyt oikeasti versionhallinnassa
- **Phase 11d**: Testit ja CI:
  - pytest-testipohja (`backend/tests/`, `requirements-dev.txt`): in-memory SQLite, auth-override user A / user B, kaikki ulkoiset kutsut mockattu
  - Testit: Leads CRUD + duplikaattiesto, tenant-isolaatio (liidit, draftit, hakuhistoria → 404), /search mock-tila + hakuhistoria, generate-email mockatulla OpenAI:lla + Deep Scan -cache, CSV-export vain omat, grid-pisteet + 50 km säderaja, MAX_SEARCH_CALLS / MAX_DETAIL_CALLS -turvakytkimet
  - Bugi: PATCH /leads/{id} päivittää nyt `updated_at`-kentän
  - Bugi: `PipelineContext.refresh` käytti vanhentunutta `session`-arvoa (tyhjä `useCallback`-deps) → liidilista saattoi jäädä tyhjäksi kirjautumisen jälkeen
  - Bugi: `EmailDraftModal.fetchDraft` `useCallback`-hookiin oikeilla riippuvuuksilla
  - GitHub Actions CI (`.github/workflows/ci.yml`): pytest + npm lint + build push/PR-eventeillä
- **Phase 12a**: Places API (New) + pisteytys:
  - Alembic käyttöön (`alembic==1.20.1`): alkumigraatio nykyskeemalle, `create_all` enää vain dev-SQLitessä, migraatiotesti CI:hin
  - Nearby Search + Place Details → Places API (New) Text Search (`places:searchText`), field mask 10 kenttää + nextPageToken, grid `locationRestriction.rectangle` -ruuduilla, max 3 sivua/ruutu
  - MAX_SEARCH_CALLS säieturvalliseksi, MAX_DETAIL_CALLS ja ScannedPlace-cache poistettu (migraatio pudottaa taulun)
  - CLOSED_PERMANENTLY suodatetaan, CLOSED_TEMPORARILY merkitään
  - `lead_score()` (0–100) omaan moduuliin + yksikkötestit; Lead-tauluun rating, review_count, business_status, primary_type, maps_url, lead_score
  - `/search`: score-järjestys + `already_saved`-merkintä
  - UI: score-badge, rating, Maps-linkki, In pipeline, järjestettävät sarakkeet; PipelineCard score + rating
- **Phase 12b**: Pisteytyksen kalibrointi ja sivuanalyysi:
  - Korjaukset: psycopg (v3) -ajuri + `normalize_database_url()`; migraatio `b128a7a9e0bd` muuntaa vanhan Supabasen naiivit TIMESTAMP-sarakkeet TIMESTAMPTZ:ksi (Postgres-testit `TEST_POSTGRES_URL`:lla)
  - `analyze_website` uusiksi (`app/utils/website_check.py`): selaimen UA, redirectit, 8 s + 1 retry, uudet tilat INSECURE ja UNKNOWN, parkkisivujen tunnistus, `Lead.website_issue` (migraatio `11b71478b845`) UI:hin ja AI-promptiin
  - Pisteytys: suosio kerrotaan sivun tilan painolla (WEBSITE OK max 20), NO_REVIEWS_PENALTY 15, INSECURE = NOT MOBILE -taso, UNKNOWN neutraali 50
  - Mukautuva ruudukko: ensin koko kaupunki yhdellä kyselyllä, vain täyttyneet alueet jaetaan 2x2 (max syvyys 2); Kauniainen 10 → 3 kutsua (~$0.32 → ~$0.075)
  - `/search` palauttaa `usage`-tiedot (kutsut + kustannusarvio), UI näyttää ne hakutulosten yläpuolella

## Seuraavaksi

### Phase 11b: Supabase RLS -policyt (tulevaisuudessa)

Jos PostgREST-pääsy Supabaseen avataan frontille ohi FastAPI-backendin, sovellustason `user_id`-suodatus ei enää riitä. Silloin:

- Ota RLS käyttöön: `ALTER TABLE lead ENABLE ROW LEVEL SECURITY;` (sama `email_draft`, `search_history_entry`)
- Policy per taulu: `CREATE POLICY "users see own rows" ON lead FOR ALL USING (user_id = auth.uid()::text) WITH CHECK (user_id = auth.uid()::text);`
- Huom: `user_id` on tällä hetkellä `str` (Supabase UUID string-muodossa), ei `uuid` — casting `auth.uid()::text` vaaditaan. Vaihtoehto: migroi `user_id` PostgreSQL `uuid`-tyypiksi tuotantoa varten
- Nyt backend on ainoa reitti dataan → sovellustason suodatus riittää, RLS on defense-in-depth

### Phase 13: Pilvideployaus (Myöhemmin)

- Backend deployaus pilveen (Render / Fly.io / Railway)
- Frontend deployaus (Vercel / Netlify / Cloudflare Pages)
- CI/CD-putki (GitHub Actions)
- Monitorointi ja lokitus (Sentry / Logflare)

## Backlog (tulevaisuuden ideat)

- **Lead Detail SlideOver** — Klikkaa liidin nimeä → oikealle liukuva paneeli (kaikki tiedot, muistiinpanohistoria, generoidut draftit, timeline)
- **Sähköpostin seuranta** — Onko vastaanottaja avannut viestin (tracking pixel / webhook)
- **Bulk Email Send** — Lähetä SMTP-sähköpostit kaikille valituille liideille kerralla toolbarista
