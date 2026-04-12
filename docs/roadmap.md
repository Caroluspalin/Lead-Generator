# Agency Hunter — Roadmap

## Tehty

- **Phase 1-3**: Perus-MVP — FastAPI + React, Google Text Search, Lead CRUD, pipeline-hallinta
- **Phase 4**: UI-yhtenäistäminen — lucide-react, englanninkielinen UI, Tailwind-pohjaiset komponentit
- **Phase 5**: Hakualgoritmin laajennus — 3x3 grid search, dynaaminen säde, turvakytkimet (15+40), asyncio.to_thread, 60s frontend timeout
- **Phase 6**: AI-sähköpostiavustaja — OpenAI GPT-4o-mini, POST /leads/{id}/generate-email, EmailDraftModal, instruction-parametri iteroinnille, copy to clipboard
- **Phase 7**: ScannedPlace Caching — `ScannedPlace`-taulu, Details API -kutsujen deduplikaatio tietokantapohjaisella cachella
- **Phase 8a**: Pipeline-navigointi — Chevron-napit (< >) dropdownin sijaan, yhden klikkauksen stage-siirto

## Käynnissä

### Phase 8: UX ja Workflow-optimointi

- Datan vienti (CSV/Excel export), jotta liidit saa helposti ulos järjestelmästä
- **Bulk Actions** — Valitse useita liidejä checkboxeilla: "Generate All Emails", "Export Selected", "Move to Stage X"
- **Lead Detail SlideOver** — Klikkaa liidin nimeä → oikealle liukuva paneeli (kaikki tiedot, muistiinpanot, generoidut sähköpostit, timeline)

### Phase 9: AI Deep Scan (Edistynyt personointi)

- Moottori laajennetaan lukemaan kohdeyrityksen verkkosivujen tekstiä (scraping)
- Tekoäly (OpenAI) käyttää sivuilta luettua dataa (esim. arvot, palvelut) luodakseen hyper-personoituja "jäänmurtaja"-lauseita sähköposteihin, sen sijaan että se vain huomauttaisi rikkinäisistä sivuista

### Phase 10: Tuotanto ja Skaalaus (Myöhemmin)

- Siirtyminen SQLitestä Supabaseen/PostgreSQL:ään
- Käyttäjien autentikaatio
- Palvelimen vieminen pilveen (Render/Heroku)

## Backlog (tulevaisuuden ideat)

- **Sähköpostin lähetys** — SMTP-integraatio suoraan sovelluksesta (draft → send)
- **SearchHistory** — Näytä aiemmat haut (hakusana + kaupunki + tulosmäärä + päivämäärä), yhden klikkauksen uudelleenhaku
- **Dashboard-analytiikka** — Konversioasteet pipeline-vaiheittain
