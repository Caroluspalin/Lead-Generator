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

## Seuraavaksi

### Phase 11b: Supabase RLS -policyt (tulevaisuudessa)

Jos PostgREST-pääsy Supabaseen avataan frontille ohi FastAPI-backendin, sovellustason `user_id`-suodatus ei enää riitä. Silloin:

- Ota RLS käyttöön: `ALTER TABLE lead ENABLE ROW LEVEL SECURITY;` (sama `email_draft`, `search_history_entry`)
- Policy per taulu: `CREATE POLICY "users see own rows" ON lead FOR ALL USING (user_id = auth.uid()::text) WITH CHECK (user_id = auth.uid()::text);`
- `ScannedPlace` pysyy RLS:ttä (tai policy `USING (true)` lukuun, ei kirjoitusta clientille)
- Huom: `user_id` on tällä hetkellä `str` (Supabase UUID string-muodossa), ei `uuid` — casting `auth.uid()::text` vaaditaan. Vaihtoehto: migroi `user_id` PostgreSQL `uuid`-tyypiksi tuotantoa varten
- Nyt backend on ainoa reitti dataan → sovellustason suodatus riittää, RLS on defense-in-depth

### Phase 12: Pilvideployaus (Myöhemmin)

- Backend deployaus pilveen (Render / Fly.io / Railway)
- Frontend deployaus (Vercel / Netlify / Cloudflare Pages)
- CI/CD-putki (GitHub Actions)
- Monitorointi ja lokitus (Sentry / Logflare)

## Backlog (tulevaisuuden ideat)

- **Lead Detail SlideOver** — Klikkaa liidin nimeä → oikealle liukuva paneeli (kaikki tiedot, muistiinpanohistoria, generoidut draftit, timeline)
- **Sähköpostin seuranta** — Onko vastaanottaja avannut viestin (tracking pixel / webhook)
- **Bulk Email Send** — Lähetä SMTP-sähköpostit kaikille valituille liideille kerralla toolbarista
