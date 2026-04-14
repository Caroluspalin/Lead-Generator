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
  - Supabase Auth + JWT-verifiointi backendissä (`backend/app/auth.py`, PyJWT, HS256)
  - Kaikki kirjoittavat + liidien luku/draftit/history-endpointit suojattu `verify_token`-dependencyllä
  - Frontend: `@supabase/supabase-js`, `AuthContext`, `Login`-komponentti, `apiFetch`-helper JWT-injektioon
  - CORS rajoitettu `ALLOWED_ORIGINS`-env-muuttujalla
  - `.env.example`-tiedostot sekä backendille että frontendille

## Seuraavaksi

### Phase 11: Pilvideployaus (Myöhemmin)

- Backend deployaus pilveen (Render / Fly.io / Railway)
- Frontend deployaus (Vercel / Netlify / Cloudflare Pages)
- CI/CD-putki (GitHub Actions)
- Monitorointi ja lokitus (Sentry / Logflare)
- Row Level Security (RLS) Supabase-kantaan, jotta käyttäjät näkevät vain omat liidinsä

## Backlog (tulevaisuuden ideat)

- **Lead Detail SlideOver** — Klikkaa liidin nimeä → oikealle liukuva paneeli (kaikki tiedot, muistiinpanohistoria, generoidut draftit, timeline)
- **Sähköpostin seuranta** — Onko vastaanottaja avannut viestin (tracking pixel / webhook)
- **Bulk Email Send** — Lähetä SMTP-sähköpostit kaikille valituille liideille kerralla toolbarista
