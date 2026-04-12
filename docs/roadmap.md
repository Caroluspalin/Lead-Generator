# Agency Hunter — Roadmap

## Tehty

- **Phase 1-3**: Perus-MVP — FastAPI + React, Google Text Search, Lead CRUD, pipeline-hallinta
- **Phase 4**: UI-yhtenäistäminen — lucide-react, englanninkielinen UI, Tailwind-pohjaiset komponentit
- **Phase 5**: Hakualgoritmin laajennus — 3x3 grid search, dynaaminen säde, turvakytkimet (15+40), asyncio.to_thread, 60s frontend timeout
- **Phase 6**: AI-sähköpostiavustaja — OpenAI GPT-4o-mini, POST /leads/{id}/generate-email, EmailDraftModal, instruction-parametri iteroinnille, copy to clipboard

## Seuraavaksi

### Phase 7: ScannedPlace Caching

**Ongelma**: Jokainen haku tekee uudet Google API -kutsut samoille yrityksille. Toistuvat haut samaan kaupunkiin/toimialaan kuluttavat API-krediittejä turhaan.

**Ratkaisu**: Uusi `ScannedPlace`-taulu tietokantaan.
- Tallenna jokaisen haun tulokset (place_id, name, address, phone, website, website_status, city, business_type, scanned_at)
- Ennen Google API -kutsua tarkista onko vastaava haku tehty esim. viimeisen 7 päivän sisällä
- Jos tuoreet tulokset löytyvät kannasta, palauta ne suoraan ilman API-kutsua
- Frontend ei muutu — sama vastausformaatti

**Hyödyt**: Vähentää Google API -kutsuja merkittävästi, nopeuttaa toistuvia hakuja sekunteista millisekunteihin.

## Backlog (tulevaisuuden ideat)

- **Sähköpostin lähetys** — SMTP-integraatio suoraan sovelluksesta (draft → send)
- **Bulk-toiminnot** — Valitse useita liidejä ja generoi/lähetä sähköpostit kerralla
- **CSV-export** — Lataa pipeline-data taulukkolaskentaan
- **Käyttäjähallinta** — Auth + monen käyttäjän tuki
- **PostgreSQL tuotantoon** — Docker Compose -pohjainen deploy
- **Hakuhistoria** — Näytä aiemmat haut ja niiden tulokset
- **Dashboard-analytiikka** — Konversioasteet pipeline-vaiheittain
