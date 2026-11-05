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
| website_status | str? | NO WEBSITE / BROKEN WEBSITE / INSECURE / NOT MOBILE / WEBSITE OK / UNKNOWN (ks. Sivuanalyysi) |
| website_issue | str? | Lyhyt syy, esim. "SSL certificate expired", "HTTP 500", "parked domain", "DNS not resolving" |
| website_context | str? | Deep Scan: skraapattu verkkosivun leipäteksti (max 2000 merkkiä) |
| scraped_at | datetime? | Deep Scan: milloin verkkosivun teksti haettiin |
| email | str? | Vain yrityksen sivustolta oikeasti löytynyt osoite (ei arvailua) tai käsin PATCHilla asetettu |
| email_source | str? | Mistä löytyi, esim. "mailto on /yhteystiedot", "obfuscated on /" |
| do_not_contact | bool | Oletus false (server_default). true estää draftin, puhelinskriptin ja lähetyksen (409) |
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

### SenderProfile

| Kentta | Tyyppi | Huom |
|---|---|---|
| id | int, PK, auto | |
| user_id | str, unique, index | Yksi profiili per käyttäjä |
| name | str | Pakollinen. Allekirjoitus + "kuka olen" sähköposteissa ja puheluissa |
| company_name | str? | Tyhjä → esiinnytään omalla nimellä |
| phone | str? | Allekirjoitukseen |
| website | str? | Portfolio, allekirjoitukseen |
| short_intro | str | Pakollinen, esim. "teen nettisivuja paikallisille yrityksille Espoossa" |
| updated_at | datetime | UTC |

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
| GET | `/search?business_type=X&city=Y` | Mukautuva grid-haku Places API (New):lla (mock dev-modessa). Palauttaa `{results, usage}`: `results` `lead_score`-järjestyksessä (paras ensin), jokaisella `already_saved: bool` ja `website_issue`; `usage` = `api_calls`, `geocode_calls`, `text_search_calls`, `estimated_cost_usd` (listahinta) |
| POST | `/leads` | Tallenna liidi kantaan (Places-kentät mukaan, `lead_score` lasketaan serverissä). Jos sivu toimii (WEBSITE OK / NOT MOBILE / INSECURE), sähköpostihaku käynnistyy taustalla vastauksen jälkeen |
| POST | `/leads/{lead_id}/find-email` | Hae sähköposti heti liidin sivustolta (422 jos sivu ei toimi). Palauttaa päivitetyn liidin; `email` null = ei löytynyt |
| GET | `/leads` | Hae kaikki tallennetut liidit |
| GET | `/leads/export?ids=1,2,3` | CSV-export valituille liideille |
| PATCH | `/leads/{lead_id}` | Päivitä status, notes, phone, website, email, do_not_contact (päivittää `updated_at`) |
| DELETE | `/leads/{lead_id}` | Poista liidi |
| POST | `/leads/{lead_id}/generate-email` | AI-sähköpostiluonnos (GPT-4o-mini) opt-out-rivillä, tallentaa draftin kantaan. 409 jos do_not_contact |
| POST | `/leads/{lead_id}/generate-call-script` | 30 s puhelinrunko suomeksi (GPT-4o-mini), ei tallennu, ei scrapingia. 409 jos do_not_contact |
| GET | `/leads/{lead_id}/drafts` | Hae liidin tallennetut sähköpostiluonnokset |
| GET | `/search-history` | 50 viimeisintä hakua |
| DELETE | `/search-history/{entry_id}` | Poista hakumerkintä |
| GET | `/sender-profile` | Käyttäjän lähettäjäprofiili (404 jos puuttuu) |
| PUT | `/sender-profile` | Luo/päivitä profiili (name + short_intro pakollisia, tyhjät valinnaiset → null) |
| POST | `/send-email` | Lähetä sähköposti SMTP:llä (`to`, `subject`, `body`, valinnainen `lead_id`). 409 jos `lead_id`:n liidi tai vastaanottajaosoite kuuluu käyttäjän do_not_contact-liidille |

## Tekniset valinnat

- **Google-haku (Places API New), mukautuva ruudukko**: Geocoding API → kaupungin viewport → yksi `POST places.googleapis.com/v1/places:searchText` koko viewportille (`locationRestriction.rectangle`, `textQuery`=toimiala, `pageSize` 20, `languageCode`/`regionCode` fi, `pageToken`-sivutus max 3 sivua). Jos alue täyttyy (60 tulosta = API:n maksimi, alueella voi olla lisää), se jaetaan 2x2 neljännekseen (`split_rectangle`, ei aukkoja/limitystä) ja vain täyttyneet neljännekset jaetaan edelleen (leveyshaku, `MAX_SPLIT_DEPTH=2` → max 1+4+16 aluetta). Deduplikaatio place id:llä → CLOSED_PERMANENTLY pois → `merge_duplicates()`: sama normalisoitu nimi (casefold, välimerkit ja ylimääräiset välit pois) JA sama puhelin (numerot, +358/00358 → 0) = yksi tulos, säilytetään se jolla enemmän arvosteluja (pelkkä nimi ei riitä, ketjuilla useita toimipisteitä; ilman puhelinta ei yhdistetä). Ei Details-kutsuja. Pieni kaupunki = 1 Geocoding + 1–3 Text Search -sivua
- **Field mask** (`PLACES_FIELD_MASK`, `X-Goog-FieldMask`-header): places.id, displayName, formattedAddress, nationalPhoneNumber, websiteUri, rating, userRatingCount, businessStatus, primaryType, googleMapsUri + nextPageToken. Field mask määrää hinnan: rating/userRatingCount/websiteUri/nationalPhoneNumber ovat **Text Search Enterprise** -kenttiä, ja koko pyyntö laskutetaan korkeimman SKU:n mukaan
- **Hinta-arvio** (Googlen hinnasto 11/2026, 0–100k-taso): Text Search Enterprise $35 / 1000 (1000 ilmaista/kk), Geocoding $5 / 1000 (10 000 ilmaista/kk). Pahin tapaus per haku = 1 Geocoding + 14 Text Search = ~$0.50. Kauniainen (parturi): vanha 3x3-grid 10 kutsua ≈ $0.32 → mukautuva 3 kutsua ≈ $0.075. Dokumentaatio ei kerro erikseen sivutuksen laskutusta — arvio olettaa jokaisen sivun omaksi pyynnökseen. Hinnat: `PRICE_PER_CALL_USD` main.py:ssä; UI näyttää listahinnan ennen ilmaiskiintiötä
- **Ei Places-sisällön välimuistia**: Googlen ehdot rajoittavat sisällön tallentamista; place id saa tallentaa pysyvästi. Places-kentät tallentuvat Lead-tauluun vain kun käyttäjä itse lisää liidin pipelineen
- **Turvakytkin**: MAX_SEARCH_CALLS=15 — ehdoton raja Geocoding + Text Search -kutsuille per haku. Laskuri on säieturvallinen (`threading.Lock`, varaus ennen kutsua)
- **Blokkauksen esto**: `asyncio.to_thread()` kaikille blokkaaville kutsuille (Google API, OpenAI, SMTP)
- **Rinnakkaisuus**: `ThreadPoolExecutor(max_workers=5)` website-analyysille; Google-alueet haetaan peräkkäin (ennustettava budjetin käyttö)
- **Sivuanalyysi** (`app/utils/website_check.py`, `analyze_website(url) -> WebsiteCheck(status, issue)`): tavallinen selaimen User-Agent + `Accept-Language: fi`, uudelleenohjaukset seurataan, timeout 8 s + 1 uudelleenyritys. HTTPS kokeillaan ensin (moni Googlen websiteUri on http://). Tilat:
  - `NO WEBSITE`: websiteUri puuttuu, tai osoite on somesivu (facebook.com myös m./www., fb.com, fb.me, instagram.com, linktr.ee) → issue "social media only". Someen ei tehdä pyyntöä lainkaan
  - `BROKEN WEBSITE`: DNS ei ratkea, yhteys hylätty (myös HTTP:llä), 404/410/5xx, parkkisivu tai domain myynnissä (tunnetut parkkipalvelut `PARKING_HOSTS` + tekstit `PARKING_MARKERS`, myös huonolla SSL:llä)
  - `INSECURE`: toimii vain HTTP:llä, HTTPS ohjaa HTTP:lle, tai SSL-sertifikaatti vanhentunut / väärä hostname / self-signed. Jos lisäksi viewport puuttuu, issue mainitsee molemmat
  - `NOT MOBILE`: ei `<meta name="viewport">`
  - `UNKNOWN`: 401/403/429, muu 4xx, Cloudflare/DDoS-haastesivu (tunnistus vain `<title>`/`cf-mitigated`-headerista — reCAPTCHA ja Cloudflaren challenge-platform-skripti ovat yleisiä toimivillakin sivuilla) tai timeout uudelleenyrityksen jälkeen. Ei koskaan pisteytetä rikkinäiseksi, eikä AI-meili saa väittää sivua rikki
  - `WEBSITE OK`
- **Frontend timeout**: 60s AbortController, dynaaminen latausteksti sekuntilaskurilla
- **AI-sähköpostit**: malli `EMAIL_MODEL` (oletus gpt-4o-mini) + valinnainen `EMAIL_REASONING_EFFORT`; `chat_completion_params()` käyttää `max_completion_tokens`-parametria ja jättää `temperature`:n pois kun reasoning effort ≠ none (OpenAI: GPT-6-malleilla temperature vain effort none -tilassa), reasoningille +4000 tokenin vara. Vaatii lähettäjäprofiilin (428 jos puuttuu). Draftit tallentuvat kantaan.
  - Prompti (`EMAIL_SYSTEM_PROMPT`): te-muoto johdonmukaisesti; 1. lause = kuka olen (profiili) + miten löysin yrityksen (toimiala + kaupunki); havainto omana varmana havaintona ilman "saattaa"-arvailua; yksi lause miksi sillä on väliä (`WHY_IT_MATTERS`-vihje, ei pelottelua); pieni konkreettinen tarjous (`OFFERS`: NO WEBSITE → ilmainen luonnos, BROKEN → katson mistä vika johtuu, INSECURE → "korjaus on yleensä nopea", NOT MOBILE → näytän miltä näyttäisi puhelimella, muut → `DEFAULT_OFFER`); jäänmurtaja Deep Scanista vain jos jotain konkreettista ja erityistä; max ~90 sanaa (`MAX_EMAIL_WORDS`)
  - Havainto: `describe_website_problem(status, issue)` → te-muotoinen havainto (`ISSUE_DESCRIPTIONS`, esim. DNS → "Googlen kautta löytyvä nettisivuosoitteenne ei avaudu", SSL → "kun avasin sivunne, selain varoitti, ettei yhteys ole turvallinen", social → "löysin teidät vain Facebookista"); malli ei näe teknistä syytä. UNKNOWN / WEBSITE OK → "ei varmistettua ongelmaa"
  - Koodissa: mallin oma lopputervehdys/[Nimesi] poistetaan (`strip_model_sign_off`), sitten "Terveisin," + allekirjoitus profiilista (`build_signature`: nimi, yritys, puhelin, sivusto) + `OPT_OUT_LINE`. Subject `email_subject()`: lyhyt ja luonnollinen ("Kysymys nettisivuista", "Löysin teidät Facebookista", "Nettisivunne ei aukea", "Huomasin jotain sivuistanne", "Sivunne puhelimella", "Kysymys nettisivuistanne")
  - Laatuvahti `check_generated_text()` lokittaa WARNING-tason varoituksen (ei estä): kielletyt sanat (`FORBIDDEN_PATTERNS`: ihana, upea, mahtava, ainutlaatuinen, intohimo, ratkaisu, kokonaisvaltainen, digitaalinen läsnäolo, seuraavalle/uudelle tasolle, innovatiivinen, räätälöity, huippu-, saumaton, synergia, liiketoiminnan kasvu, keskustella tarkemmin, saattaa), yli ~110 sanaa, euromäärät
- **Puhelinskripti** (`CALL_SCRIPT_SYSTEM_PROMPT`): sama malli, profiili ja havainto; rakenne 1. Avaus (nimi + esittely + "Onko teillä hetki, vai soitanko myöhemmin?") → 2. Havainto (yksi arkikielinen lause) → 3. Tarjous + yksi suora kysymys (ei konsulttimaisia kysymyksiä) → 4. Jos "ei kiinnosta": täsmälleen "Selvä, kiitos ajastanne, mukavaa päivää!" → 5. Jos kysyvät hintaa: riippuu tarpeesta + ehdota luonnosta/tapaamista, ei euromääriä. Ei scrapingia eikä Deep Scan -sisältöä
- **Do not contact**: `Lead.do_not_contact` estää generate-email, generate-call-script ja send-email (409). UI: "Mark do not contact" / "Allow contact again" PipelineCardissa, AI Draft ja Call script disabloitu
- **Yhteystietohaku** (`app/utils/contact_finder.py`, `find_contact_email(website) -> ContactEmail(email, source) | None`): `website_check.fetch_page()` samoilla UA/timeout/retry/SSL-säännöillä kuin sivuanalyysi. Etusivu + max 3 samalla sivustolla olevaa linkkiä, joiden teksti tai polku sisältää `CONTACT_KEYWORDS` (yhteystiedot, ota-yhteytta, contact, kontakt...). Ei muuta crawlausta. Poimii mailto-linkit, tekstin, peitetyt muodot (`(at)`, `[at]`, `{at}`, `(ät)`, `(dot)`, `(piste)`) ja Cloudflare Email Protectionin. Scriptit/style ohitetaan; kuvatiedostonimet, esimerkkiosoitteet (example.*, domain.fi, nimi@...), noreply ja sentry/wixpress pois. Järjestys: oma domain > yleinen osoite (`GENERIC_LOCAL_PARTS`: info, asiakaspalvelu, myynti...) > löytöjärjestys. Ei arvailua eikä ulkoisia palveluita. Ajetaan aina taustasäikeessä (`asyncio.to_thread`); POST /leads käyttää `BackgroundTasks`:ia, jotta tallennus ei odota (pahimmillaan 4 sivua × 8 s × 2)
- **SMTP-lähetys**: Suora sähköpostin lähetys EmailDraftModalista, konfiguroidaan .env:ssä
- **Pipeline-navigointi**: Chevron-napit (< >) dropdownin sijaan, yhden klikkauksen stage-siirto
- **Bulk Actions**: Leijuva toolbar — Move Stage, AI Drafts, CSV Export, Delete valituille liideille (erissä, 5 kerrallaan)
- **Deep Scan**: Verkkosivun leipätekstin scraping (requests + BeautifulSoup, 5s timeout) → teksti cachetetaan Lead.website_context -kenttään → OpenAI käyttää sitä personoitujen jäänmurtajien generointiin sähköposteihin. Vikasietoinen: jos scraping epäonnistuu, meili generoidaan ilman personointia
- **Auth**: Supabase Auth + JWT. Frontend käyttää `@supabase/supabase-js`, session tallentuu selaimeen, access_token lisätään automaattisesti `apiFetch`-helperillä Authorization-headeriin. Backend verifioi JWT:n (`backend/app/auth.py`, `verify_token`-dependency) tukien sekä uusia ES256/RS256-tokeneita JWKS-endpointista (`PyJWKClient`, `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, avainten cache, macOS-venvissä certifi-SSL-context) että legacy-HS256-tokeneita `SUPABASE_JWT_SECRET`-salaisuudella. Algoritmi tunnistetaan tokenin headerista. `AUTH_DISABLED=true` ohittaa verifioinnin dev-kehityksessä. SidebarNav näyttää kirjautuneen käyttäjän emailin ja sign-out-napin
- **Multi-tenancy**: Lead, EmailDraft ja SearchHistoryEntry sisältävät `user_id`-kentän (Supabase UUID, indexed). Kaikki endpointit suodattavat `user_id == current_user.id`: GET-listat `.where(user_id)`, PATCH/DELETE/single-GET palauttavat 404:n (ei 403:a) jos toisen käyttäjän resurssia yritetään käyttää — ei paljasta resurssien olemassaoloa. POST-operaatiot asettavat `user_id` serverissä `AuthUser.id`:stä (ei clientin syötteestä). `Lead.google_place_id` ei ole enää globaalisti unique — `UniqueConstraint("google_place_id", "user_id")` sallii saman yrityksen useammalle käyttäjälle.
- **Aikaleimat**: Kaikki datetime-kentät luodaan aikavyöhykkeellisinä (`models.utc_now()` = `datetime.now(timezone.utc)`). Uudet SQLModel-versiot hylkäävät naive-datetimet. Älä käytä `datetime.utcnow()`:ia
- **Käynnistys**: FastAPI:n `lifespan`-handler kutsuu `create_db_and_tables()`, joka ajaa `create_all`:n vain dev-SQLitessä
- **Migraatiot (Alembic)**: `backend/alembic.ini` + `backend/migrations/` (`render_as_batch=True` SQLiteä varten, URL `app.database.engine`:stä eli `DATABASE_URL`:sta). Postgresissa skeema vain `alembic upgrade head`:lla. Ketju: `5c3252fb0873` alkuskeema → `a37cda0e085d` ScannedPlace pois → `ab965e378f8b` Lead Places-kentät + lead_score → `b128a7a9e0bd` datetime-sarakkeet TIMESTAMPTZ:ksi (vain Postgres, vain naiivit sarakkeet; SQLite no-op) → `11b71478b845` Lead.website_issue → `af5c0e76b864` Lead.email, email_source, do_not_contact (server_default false olemassa oleville riveille) → `e0c769279b9e` SenderProfile-taulu. `tests/test_migrations.py` ajaa upgrade + `alembic check` + downgrade/upgrade-kierroksen, joten unohtunut migraatio kaataa CI:n
- **Olemassa oleva Supabase-kanta** (luotu `create_all`:lla ennen Alembicia): aja kerran `alembic stamp 5c3252fb0873`, sitten `alembic upgrade head`, sitten `alembic check`. Vanhat taulut luotiin `timestamp without time zone` -sarakkeilla; migraatio `b128a7a9e0bd` muuntaa ne `timestamptz`:ksi (`USING col AT TIME ZONE 'UTC'`, arvot olivat naiiveja UTC-aikoja). Migraatio tarkistaa `information_schema`:sta ja muuntaa vain naiivit sarakkeet, koska jo-tz-sarakkeille sama USING siirtäisi arvoja session aikavyöhykkeen verran. Downgrade palauttaa `timestamp without time zone`
- **Postgres-ajuri**: psycopg (v3). `normalize_database_url()` muuttaa `postgres://` ja `postgresql://` muotoon `postgresql+psycopg://`. `engine_options()` antaa Postgresille `connect_args={"prepare_threshold": None}`: Supabasen transaction pooler (portti 6543) ei tue prepared statementeja, joita psycopg3 muuten alkaa käyttää 5. toistetun kyselyn jälkeen
- **Postgres-migraatiotestit**: `TEST_POSTGRES_URL=postgresql://... pytest tests/test_migrations.py` ajaa legacy-kanta-simulaation (naiivit sarakkeet, session TZ Europe/Helsinki) ja tuoreen kannan tarkistuksen. Ilman muuttujaa testit ohitetaan (CI). **Testit tyhjentävät `public`-skeeman — älä koskaan osoita niitä Supabaseen**, vain paikalliseen kertakäyttökantaan (esim. `docker run --rm -e POSTGRES_PASSWORD=test -p 127.0.0.1:55432:5432 postgres:15`)
- **Riippuvuudet**: `backend/requirements.txt` lukittu tarkkoihin versioihin (`==`), testattu Python 3.13:lla puhtaassa venvissä. Päivitä versioita tietoisesti, ei automaattisesti
- **Testit**: pytest + FastAPI TestClient (`backend/tests/`, dev-riippuvuudet `backend/requirements-dev.txt`). `conftest.py` asettaa env-muuttujat ennen app-importtia (ei `backend/.env`:n oikeita avaimia/kantaa), käyttää in-memory SQLiteä (StaticPool) ja `dependency_overrides`-mekanismia `get_session`- ja `verify_token`-dependencyille. Käyttäjä valitaan `X-Test-User`-headerilla (`client_a` / `client_b` -fixturet) tenant-isolaation testaamiseen. Autouse-fixture estää oikeat kutsut (requests, OpenAI, scraping, SMTP); testit mockaavat tarvitsemansa
- **CI**: GitHub Actions (`.github/workflows/ci.yml`) push- ja pull_request-eventeillä: backend (Python 3.13, pytest) ja frontend (Node 22, `npm ci` + lint + build). Ei API-avaimia
- **UI hakutuloksille**: LeadTable — score-badge (75+ vihreä, 50+ lime, 25+ keltainen, muuten harmaa), rating + arvostelumäärä, Google Maps -linkki, "Temporarily closed" -merkintä, "In pipeline" jo tallennetuille (Save-nappi piilossa), `website_issue` status-badgen alla. Oletusjärjestys score desc, sarakkeet Score/Business/Rating/Status klikattavia (Status: NO WEBSITE > BROKEN > INSECURE > NOT MOBILE > UNKNOWN > OK). Hakutulosten yläpuolella "N API calls, ~$X" (mock: "Mock data, 0 API calls"). PipelineCard näyttää scoren, ratingin ja issuen. Dashboardin "opportunity"-luku ei laske UNKNOWN-tilaa
- **Tietokanta**: Dev SQLite, tuotanto PostgreSQL (Supabase). `DATABASE_URL` tukee `postgres://`- ja `postgresql://`-muotoja, Postgresissa pool_pre_ping + pool_size=5

## Pisteytys (lead_score)

`backend/app/scoring.py`, puhdas funktio `lead_score(website_status, rating, review_count, business_status) -> int` (0–100). Periaate: paras liidi on toimiva, suosittu yritys jolla on huono tai puuttuva nettisivu. Suosio **kerrotaan** sivun tilan painolla eikä lisätä summaan, joten suosittu yritys toimivalla sivulla ei voi nousta kuumaksi liidiksi. Kaikki painot ovat moduulin vakioita — säädä niitä ja aja `pytest tests/test_scoring.py`.

```
jos business_status == CLOSED_PERMANENTLY:  score = 0
reviews = review_count tai 0   (Google jättää kentän pois kun arvosteluja ei ole)

popularity (0-1) = 0 jos reviews == 0, muuten
    REVIEW_WEIGHT * min(1, ln(1+reviews) / ln(1+REVIEW_SATURATION))
  + RATING_WEIGHT * clamp((rating - RATING_FLOOR) / (RATING_CEIL - RATING_FLOOR)) * min(1, reviews / RATING_CONFIDENCE_REVIEWS)

score = OPPORTUNITY[website_status] * (POPULARITY_FLOOR + (1 - POPULARITY_FLOOR) * popularity)
jos reviews == 0:                     score -= NO_REVIEWS_PENALTY
jos CLOSED_TEMPORARILY:               score -= CLOSED_TEMPORARILY_PENALTY
score = clamp(round(score), 0, 100)
```

| Vakio | Arvo | Vaikutus |
|---|---|---|
| OPPORTUNITY | NO WEBSITE 100, BROKEN 90, INSECURE 65, NOT MOBILE 65, UNKNOWN 50, WEBSITE OK 20 | Sivun tilan maksimipisteet (= katto). Puuttuva/tuntematon tila = UNKNOWN |
| POPULARITY_FLOOR | 0.6 | Osuus katosta ilman suosiota |
| REVIEW_WEIGHT / RATING_WEIGHT | 0.7 / 0.3 | Suosion koostumus |
| REVIEW_SATURATION | 200 | Arvostelumäärä log-asteikolla, täysi 200:sta |
| RATING_FLOOR / RATING_CEIL | 3.0 / 5.0 | <= 3.0 ei pisteitä |
| RATING_CONFIDENCE_REVIEWS | 10 | 5.0 / 1 arvostelu ei saa täysiä rating-pisteitä |
| NO_REVIEWS_PENALTY | 15 | Ei arvosteluja: kuollut tai uusi |
| CLOSED_TEMPORARILY_PENALTY | 40 | Tilapäisesti suljettu |

UNKNOWN on neutraali (50 = asteikon keskikohta): sivun tilasta ei bonusta eikä rangaistusta, koska tilaa ei saatu varmistettua.

Esimerkkejä (Kauniainen-livedata): BROKEN 4.6/11 → 74; NO WEBSITE 4.0/1 → 64; INSECURE 5.0/10 → 55; NO WEBSITE ilman arvosteluja → 45; WEBSITE OK 4.9/340 → 20; WEBSITE OK ilman arvosteluja → 0.

Pisteet lasketaan `/search`-vastaukseen jokaiselle tulokselle ja `POST /leads`:ssä tallennettavalle liidille (clientin lähettämä arvo ohitetaan). Vanhoilla liideillä `lead_score` on tallennushetken kaavan mukainen (tai NULL ennen Phase 12a:ta) — sitä ei lasketa uudelleen automaattisesti.

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
EMAIL_MODEL=gpt-4o-mini        # suositus: gpt-6.1-terra (gpt-4o-mini poistuu 14.1.2027)
EMAIL_REASONING_EFFORT=        # GPT-6-malleille: none | low | medium | high (suositus terralle: low)
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
backend/app/utils/website_check.py — Sivuanalyysi: analyze_website() -> WebsiteCheck(status, issue); fetch_page() yhteinen sivunhaku
backend/app/utils/contact_finder.py — Yhteystietohaku: find_contact_email() -> ContactEmail(email, source)
backend/tests/conftest.py      — Testifixturet: in-memory SQLite, auth-override (client_a/client_b), verkkoesto
backend/tests/test_*.py        — Leads CRUD, tenant-isolaatio, haku + AI-email, Places API (field mask, sivutus, mukautuva ruudukko, kutsuraja), sivuanalyysi, pisteytys, migraatiot, DB-URL
.github/workflows/ci.yml       — CI: pytest + npm lint + build
src/lib/supabaseClient.ts      — Supabase-client (VITE_SUPABASE_URL + ANON_KEY)
src/lib/api.ts                 — apiFetch: lisää Authorization-Bearer-tokenin kaikkiin pyyntöihin
src/context/AuthContext.tsx    — Sessionin hallinta (signIn/signUp/signOut)
src/components/Login.tsx       — Kirjautumis- ja rekisteröitymis-lomake
src/App.tsx                    — Haku-UI, tab-navigaatio (search | pipeline | dashboard | history)
src/context/PipelineContext.tsx — Globaali tila + API-kutsut backendiin
src/components/PipelineCard.tsx — Liidikortti (checkbox, chevron-navigointi, notes, email + lähde, Find email, AI Draft, Call script, Mark do not contact)
src/components/PipelineBoard.tsx — Pipeline-kanban + Bulk Actions -toolbar
src/components/EmailDraftModal.tsx — AI-sähköpostimodaali + SMTP Send -nappi (vastaanottaja esitäytetään liidin emaililla, lähettää lead_id:n)
src/components/CallScriptModal.tsx — Puhelinskriptimodaali (generoi, regeneroi, kopioi)
src/components/DashboardView.tsx — Dashboard-analytiikka (KPI, funnel, website status)
src/components/SearchHistoryView.tsx — Hakuhistoria + re-search
src/components/AddBusinessModal.tsx — Manuaalinen liidin lisäys
src/components/SidebarNav.tsx   — Sivupalkki-navigaatio (search | pipeline | dashboard | history | settings)
src/components/SettingsView.tsx — Lähettäjäprofiilin lomake (GET/PUT /sender-profile)
src/components/LeadTable.tsx    — Hakutulosten taulukko (järjestettävät sarakkeet, score, rating, Maps, In pipeline, website_issue)
src/components/ScoreBadge.tsx   — ScoreBadge + RatingDisplay (LeadTable ja PipelineCard)
src/types/agency.ts            — SearchResponse, SearchUsage, SearchResult, Agency, SavedAgency, WebsiteStatus, BusinessStatus, PipelineStatus, NavTab
```
