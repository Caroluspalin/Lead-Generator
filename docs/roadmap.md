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
- **Phase 12c**: Yhteystiedot ja parempi outreach:
  - Korjaukset: `prepare_threshold=None` Postgres-enginelle (Supabase transaction pooler), somesivut (Facebook/Instagram/linktr.ee) → NO WEBSITE "social media only" ilman pyyntöä, hakutulosten duplikaattien yhdistäminen (nimi + puhelin)
  - Yhteystietohaku sivustolta (`contact_finder.py`): etusivu + max 3 yhteystietosivua, mailto/teksti/peitetyt/Cloudflare, oma domain ja yleiset osoitteet ensin, ei arvailua; automaattisesti taustalla pipelineen lisättäessä + Find email -nappi
  - Lead: email, email_source, do_not_contact (migraatio `af5c0e76b864`)
  - Sähköposti: havaittu ongelma selkokielellä (ei jargonia, ei pelottelua), opt-out-rivi aina lopussa
  - do_not_contact estää draftin, puhelinskriptin ja lähetyksen (409)
  - `POST /leads/{id}/generate-call-script` + CallScriptModal
- **Phase 12d**: Sähköpostit ja puhelinskriptit, jotka kuulostavat ihmiseltä:
  - SenderProfile (name, company_name, phone, website, short_intro) per käyttäjä, GET/PUT /sender-profile, Settings-näkymä; migraatio `e0c769279b9e`
  - Allekirjoitus koodissa profiilista + opt-out; 428 jos profiili puuttuu
  - Sähköpostiprompti uusiksi: te-muoto, kuka olen + miten löysin, varma havainto, miksi väliä, pieni konkreettinen tarjous, jäänmurtaja vain jos konkreettinen, max ~90 sanaa, luonnollinen subject
  - Kielletyt sanat + pituus + hinta -varoitukset lokiin (`check_generated_text`)
  - Puhelinskripti uusiksi: "onko teillä hetki", suora tarjous, kiinteä "ei kiinnosta" -vastaus, hintakysymys ilman euromääriä
  - Malli konfiguroitavaksi (`EMAIL_MODEL`, `EMAIL_REASONING_EFFORT`); live-vertailu gpt-4o-mini vs gpt-6.1-terra
  - Korjaus: Alembic `fileConfig(disable_existing_loggers=False)`
- **Phase 13a**: Demosivugeneraattori (Vaihe A: generointi + paikallinen esikatselu):
  - Pikakorjaukset: puhelinskripti ilman markdownia (prompti + `strip_markdown`), ei yrityksen pitkää virallista nimeä avauksessa
  - AI tuottaa vain validoidun JSON-sisällön, HTML Jinja2-pohjista (beauty / restaurant / services, 3 värimaailmaa), ei JS:ää eikä ulkoisia resursseja
  - Keksityt hinnat, numerot, sitaatit, arvostelut, palkinnot, historia ja nimet hylätään; yksi uudelleenyritys
  - Aukioloajat yhdellä Place Details (New) -kutsulla generointihetkellä
  - Demo-banneri + noindex (meta + X-Robots-Tag), tiukka CSP, arvaamaton public_token
  - Demo-malli + CRUD-endpointit, julkinen `/demo/{token}`, DemoModal UI:ssa
  - Sähköposti käyttää demolinkkiä tarjouksena, linkki lisätään koodissa
  - Hero-kuvasta karsitaan tuotteet, merkit, hyllyt ja pullot (kuvaus, alt, tagit); fallback parhaaseen + varoitusloki
  - Tekstit: arkikieli, yhden lauseen palvelukuvaukset, uudet kielletyt fraasit (autamme, tarjoamme laadukasta, tervetuloa huolehtimaan), toistuvien fraasien tarkistus koko sivulta (uudelleenyritys + varoitusloki), yläotsikko ei toista yrityksen nimeä
  - Visuaalinen ilme: Unsplash-kuvat (hero + 2–3 tunnelmakuvaa, attribuutio, hotlinking, download tracking, kuvanvalitsin modaalissa, gradientti fallbackina), otsikkofontti per pohja upotettuna, yrityksen nimi heron päätasona, palvelukohtaiset ikonit, ruudukko ilman yksinäistä korttia, ohut demobanneri, mobiilin kiinteä soittonappi
- **Phase 13b**: Demojen julkaisu (Cloudflare R2 + Worker):
  - `boto3==1.43.118` S3-API:lla R2:een, Worker `wrangler@4.152.0` palvelee `/{token}` R2-bindingistä samoilla suojaheadereilla, 410 vanhentuneelle
  - Publish / Unpublish -endpointit ja UI, julkaistu versio päivittyy muokatessa, poisto R2:sta demon/liidin poistossa
  - Automaattinen vanheneminen 30 pv (Hired-liidin demo jatketaan), lifespan-taustatehtävä
  - Sähköpostiin vain julkaistun demon linkki
  - Oma domain myöhemmin pelkällä `DEMO_PUBLIC_BASE_URL`-muutoksella + domain Workeriin Cloudflaressa
  - Workerin testit CI:hin (Node, tyyppien poisto)
- **Phase 13c**: Demo + email -ketju:
  - PipelineCardin "Demo + email": olemassa oleva demo avataan suoraan, muuten generoidaan (lataustila)
  - DemoModalin pääpainike "Publish & create email" (otsikkorivillä): julkaisu → sähköpostiluonnos julkisella linkillä, vastaanottaja esitäytetty; puuttuva sähköposti → huomautus + Call script
  - Linkki vain julkaistulle demolle (ei draft/expired/localhost), luonteva linkkilause tarjouskohtaan ilman toistoa, `require_demo_link` → 409 ilman julkaisua
  - `POST /leads/{id}/email/demo-link`: linkki jo kirjoitettuun luonnokseen ilman AI-kutsua
  - Julkaisuvirhe → selkeä viesti, ei sähköpostia; do_not_contact estää koko ketjun
  - Korjaus: testit eristetty oikeasta R2:sta ja Unsplashista (regressio + testi)
  - Selaintesti (Playwright, fake OpenAI + fake R2) kaikille vaiheille
- **Phase 14**: Sovelluksen ulkoasun uudistus (demosivut ennallaan):
  - Suunta "Mono": tumma oletusteema, neutraalit harmaat, aksentti lähes valkoinen, ohuet reunat varjojen sijaan (varjo vain modaaleissa/popovereissa), pyöristykset 4/6/8 px, tiiviimpi taulukko
  - Design tokenit: CSS-muuttujat `src/index.css` (RGB-kanavina, opacity-modifierit toimivat) → semanttiset Tailwind-nimet `tailwind.config.js` (`canvas`, `surface`, `raised`, `line`, `fg`, `accent`, `score-*`, `status-*`, `h-control`, `p-card` ...). Komponenteissa ei kovakoodattuja värejä
  - Statusvärit vain merkityksellisissä kohdissa: score (numero + ohut pistepalkki taulukossa ja kortissa) ja sivun tila (piste + teksti, yhteinen `StatusBadge`). Pipeline-vaiheet neutraaleja
  - Saavutettavuus: tekstikontrastit ≥ 4.5:1 (WCAG AA), näkyvä `:focus-visible`-rengas, linkit alleviivattu hillitysti (vahvistuu hoverilla), label/aria-attribuutit lomakkeisiin, dialogeihin ja ikoninapeille, History-rivin toiminnot näkyvät myös näppäimistöfokuksella
  - Layout: lyhyemmät navigaationimet, sivuotsikko + kuvaus, PipelineCardin yhteystiedot listana ja toiminnot yhdellä rivillä, "Pro Plan" poistettu
  - Tarkistettu Playwrightilla 1280 ja 1440 px, `docs/media`-kuvakaappaukset päivitetty
- **Phase 15**: Demolinkillinen sähköposti luotettavammaksi:
  - Luettavat demo-osoitteet `/{nimi}-{satunnainen}` (esim. `taina-lantiainen-k7x2m`), `Demo.public_slug` (migraatio `9148408efe32`); vanhat token-osoitteet toimivat, Worker hyväksyy molemmat, törmäykset käsitellään
  - Sähköpostin rakenne kun demo on julkaistu: malli kirjoittaa vain kappaleet 1–2 (kuka olen + miten löysin, mitä asiakkaalle tapahtuu nyt per ongelmatyyppi), koodi kokoaa linkin omalle rivilleen, riskittömyyden ja seuraavan askeleen; ei loppukysymystä; aihe "Tein teille luonnoksen nettisivuista"
  - `SenderProfile.brand_name` (migraatio `3d717a6775b2`) + Settings-kenttä, allekirjoitus nimi / brändi · sivusto / puhelin
- **Phase 16**: Premium-demopohjat portfolion esimerkkisivuista:
  - Uudet pohjat (versio 2): `cafe` (Paahtoaste, Pikkupaahtimo), `salon` (Kaislikko, Kaislaranta), `barber` (Kulmakyltti, Kulmapää). Valinta primary_typestä, vanhat pohjat valittavissa nimellä "Classic …". 2–3 palettia per pohja, AA-kontrastit testataan suoraan CSS:stä
  - Erilliset CSS/JS/fonttitiedostot sisällön tiivisteellä (`?v=`), R2:ssa `assets/{ryhmä}/{tiiviste}/` (ei koskaan poisteta), Worker `/a/...` immutable + CORS, CSP demon muodon mukaan (`style-src`/`script-src 'self'`, ei inlineä)
  - Aukioloajat myös koneluettavina (`periods`, sama field mask) → `aukiolo.js` "Auki nyt, sulkeutuu klo X", useampi jakso per päivä, kiinteä viikkoaikataulu ilman JS:ää
  - Sisältö: valinnainen `about_title`, pohjakohtainen price_note, väitteet joita lähdetiedoissa ei ole (sijainti, oma valmistus, perhe/omistajat, perinteet, koko) hylätään; osiot ilman dataa (hinnasto, lounas, kampaajat, sitaatti) korvattu yleisillä
  - Kuvat: pohjakohtaiset haut (kahvila: kuppi yläkulmasta + leivonnaiset, kampaamo: lopputulos, parturi: liike + työkalut), kasvoriski kuvauksesta, eläin/pörrö-kuvat pois, laitteiden lähikuvat viimeisiksi, estolista (`BLOCKED_PHOTO_IDS`) näkyville merkeille, kahvilan yhteystietoihin tumma kuva, parturissa mustavalko CSS:llä
  - Kulmakyltin jakosääntö ja varaversio, AI-otsikoiden koko rajataan pisimmän sanan mukaan (ei vaakavieritystä pitkillä yhdyssanoilla)
  - Esikatselumodaaliin automaattinen 390 px kuvakaappaus (Playwright, valinnainen), iframe `sandbox="allow-scripts"`
  - Laatuportti `backend/scripts/demo_check.py`: 6 mock-demoa, Chromium + WebKit 320–1440 px, ilman JS:ää, kuva-arkki; Lighthouse mobiili 98–100 (SEO 58 = noindex)
- **Phase 17**: Uudet liidit -haku ja nykyisen sivun sisältö demoon:
  - Hakulomake: liidimäärä (oletus 20), sivun tila -suodattimet, minimipisteet, ei suljettuja, vain uudet (oletus), naapurialueet. Haku jatkaa ruudukkoa sivu kerrallaan kunnes määrä täyttyy tai MAX_SEARCH_CALLS (ennallaan 15) tulee vastaan; yhteenveto löydetyt / pyydetyt, syy ja hinta
  - `PlaceStatus` (seen / in_pipeline / dismissed, vain place_id + tila, migraatio `cd994575ba52`); Hylkää hakutuloksissa ja pipelinessa, Asetuksissa hylättyjen lista ja palautus. Pipelinessa olevat eivät enää näy hakutuloksissa
  - Laajennettu Deep Scan osittain toimiville sivuille (robots.txt, viive, etusivu + max 3 alasivua): palvelut, hinnat ja esittely tarkistettuina `Lead.website_facts`iin (migraatio `abdec4f1ad33`). Demo käyttää niitä ensisijaisesti; hinnat vain omalta sivulta merkinnällä "Hinnat nykyiseltä sivultanne"; kuvat edelleen Unsplashista. Sähköpostiin "Tein luonnoksen nykyisten tietojenne pohjalta"

## Seuraavaksi


### Phase 11b: Supabase RLS -policyt (tulevaisuudessa)

Jos PostgREST-pääsy Supabaseen avataan frontille ohi FastAPI-backendin, sovellustason `user_id`-suodatus ei enää riitä. Silloin:

- Ota RLS käyttöön: `ALTER TABLE lead ENABLE ROW LEVEL SECURITY;` (sama `email_draft`, `search_history_entry`)
- Policy per taulu: `CREATE POLICY "users see own rows" ON lead FOR ALL USING (user_id = auth.uid()::text) WITH CHECK (user_id = auth.uid()::text);`
- Huom: `user_id` on tällä hetkellä `str` (Supabase UUID string-muodossa), ei `uuid` — casting `auth.uid()::text` vaaditaan. Vaihtoehto: migroi `user_id` PostgreSQL `uuid`-tyypiksi tuotantoa varten
- Nyt backend on ainoa reitti dataan → sovellustason suodatus riittää, RLS on defense-in-depth

### Phase 14: Pilvideployaus (Myöhemmin)

- Backend deployaus pilveen (Render / Fly.io / Railway)
- Frontend deployaus (Vercel / Netlify / Cloudflare Pages)
- CI/CD-putki (GitHub Actions)
- Monitorointi ja lokitus (Sentry / Logflare)

## Backlog (tulevaisuuden ideat)

- **Lead Detail SlideOver** — Klikkaa liidin nimeä → oikealle liukuva paneeli (kaikki tiedot, muistiinpanohistoria, generoidut draftit, timeline)
- **Sähköpostin seuranta** — Onko vastaanottaja avannut viestin (tracking pixel / webhook)
- **Bulk Email Send** — Lähetä SMTP-sähköpostit kaikille valituille liideille kerralla toolbarista
