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
| website_facts | str? (JSON) | Laajennettu Deep Scan (`SiteFacts`): palvelut, hinnat ja esittely yrityksen omalta sivulta, tarkistettu sivujen tekstiä vasten. Tyhjä JSON = skannattu ilman käyttökelpoista sisältöä (ei skannata uudelleen) |
| website_facts_at | datetime? | Milloin laajennettu Deep Scan tehtiin |
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

### PlaceStatus

Käyttäjän tila Google-paikalle. Vain `place_id` ja tila: Googlen ehdot sallivat place_id:n pysyvän tallennuksen, muuta Places-sisältöä ei tallenneta tähän tauluun (nimiä ei ole, Asetusten hylättyjen listassa on Google Maps -linkki).

| Kentta | Tyyppi | Huom |
|---|---|---|
| id | int, PK, auto | |
| user_id | str, index | Omistaja; uniikki (user_id, place_id) |
| place_id | str | Googlen place id (dev-mockissa `dev-…`; käsin lisätyillä `manual-…` ei tilaa) |
| status | str | `seen` (näytetty hakutuloksissa) / `in_pipeline` (`POST /leads`) / `dismissed` (Hylkää, pysyvä) |
| updated_at | datetime | |

Siirtymät: hakutulokset → `seen` (ei koskaan alenna in_pipeline/dismissed), `POST /leads` → `in_pipeline`, liidin poisto → `seen`, Hylkää → `dismissed` (pipelinessa myös liidi ja demo poistetaan), palautus → rivi poistetaan (paikka on taas uusi). Migraatio `cd994575ba52` merkitsee olemassa olevat Places-liidit `in_pipeline`.

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
| company_name | str? | Virallinen nimi. Tyhjä → esiinnytään omalla nimellä. Allekirjoituksessa vain jos brand_name puuttuu |
| brand_name | str? | Allekirjoituksessa näkyvä nimi, esim. "Palin Web" (max 60) |
| phone | str? | Allekirjoitukseen |
| website | str? | Portfolio, allekirjoitukseen |
| short_intro | str | Pakollinen, esim. "teen nettisivuja paikallisille yrityksille Espoossa" |
| updated_at | datetime | UTC |

### Demo

| Kentta | Tyyppi | Huom |
|---|---|---|
| id | int, PK, auto | |
| user_id | str, index | Omistaja |
| lead_id | int, unique, index | Yksi demo per liidi |
| template | str | cafe / salon / barber (versio 2) tai beauty / restaurant / services (Classic) |
| color_scheme | str | Pohjan paletti (2–3 per pohja) |
| content_json | str | DemoStoredContent JSONina: AI:n tekstit + price_note + generointihetken aukioloajat |
| html | str | Renderöity staattinen sivu |
| public_token | str, unique, index | `secrets.token_urlsafe(32)`, 43 merkkiä. Säilyy uudelleengeneroinnissa |
| public_slug | str?, unique, index | Luettava osoite `{nimi}-{satunnainen}`, esim. `taina-lantiainen-k7x2m` (`new_public_slug`). None = luotu ennen slugeja → osoite on token. Säilyy uudelleengeneroinnissa |
| status | str | draft / published / expired |
| created_at | datetime | |
| published_at | datetime? | Vaihe B |
| expires_at | datetime? | Vaihe B (30 pv jos ei Hired) |

Places-sisältö: aukioloajat haetaan vain generoinnin hetkellä ja tallentuvat vain osana demoa (ei erillistä välimuistia). Liidin poisto poistaa demon.

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
| GET | `/search?business_type=X&city=Y&count=20&status=…&min_score=0&exclude_closed=false&only_new=true&expand_neighbors=false` | "Uudet liidit": mukautuva grid-haku Places API (New):lla sivu kerrallaan, kunnes `count` (1–100) suodattimet täyttävää uutta liidiä löytyy tai MAX_SEARCH_CALLS täyttyy (mock dev-modessa). `status` toistettava: `no_website`, `broken`, `insecure`, `not_mobile` (myös INSECURE ilman viewportia), `social_only`; tyhjä = kaikki. Pipelinessa ja hylätyt suodatetaan aina pois, nähdyt jos `only_new`. `expand_neighbors`: kaupungin ruudukon jälkeen 8 samankokoista ruutua ympäriltä samaan kutsurajaan. Palauttaa `{results, usage, summary}`: `results` `lead_score`-järjestyksessä, `city` osoitteen kunnasta; `summary` = requested, found, `stop_reason` (target_reached / call_limit / area_exhausted), ohitetut (in_pipeline, dismissed, seen), filtered_out, searched_neighbors. Palautetut merkitään `seen` |
| POST | `/places/{place_id}/dismiss` | Hylkää pysyvästi (`dismissed`). Jos paikka on pipelinessa, liidi ja demo poistetaan (julkaistu demo otetaan ensin pois). 422 käsin lisätyille (`manual-`) |
| DELETE | `/places/{place_id}/dismiss` | Palauta hylätty (rivi poistetaan → näkyy taas uutena). 404 jos ei hylätty (myös toisen käyttäjän) |
| GET | `/places/dismissed` | Hylätyt: `place_id`, `maps_url` (Google Maps place_id-linkki), `dismissed_at` |
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
| GET | `/demo-templates` | Pohjat (version 2 pohjat ensin, `version`-kenttä) ja paletit |
| GET | `/leads/{lead_id}/demo/screenshot` | 390 × 844 puhelinnäkymä JPEG:nä (Playwright, välimuisti HTML:n tiivisteellä). 501 jos Playwright puuttuu |
| POST | `/leads/{lead_id}/demo` | Generoi demo (`template`/`color_scheme` valinnaisia, muuten primary_typen mukaan). 404/409 DNC/428 profiili puuttuu/502 sisältö ei läpäissyt validointia kahdesti |
| GET | `/leads/{lead_id}/demo` | Demon tiedot (ilman HTML:ää) + `preview_url` |
| PATCH | `/leads/{lead_id}/demo` | Vaihda pohja/värit ja/tai muokkaa tekstejä ilman AI-kutsua (renderöi uudelleen) |
| DELETE | `/leads/{lead_id}/demo` | Poista demo (linkki lakkaa toimimasta) |
| GET | `/demo/{public_path}` | Julkinen esikatselu ilman kirjautumista (slug tai vanha token, vain tarkka osuma): HTML + `X-Robots-Tag: noindex, nofollow`, CSP demon muodon mukaan (versio 1: `style-src 'unsafe-inline'`; versio 2: `style-src 'self'; script-src 'self'; font-src 'self'`), `no-store`. 404 tuntematon, 410 vanhentunut |
| GET | `/demo/a/{ryhmä}/{tiedosto}` | Version 2 demon CSS/JS/fontti esikatselua varten (vain paketin tiedostot, CORS `*` fonttien vuoksi) |
| POST | `/leads/{lead_id}/email/demo-link` | Lisää julkaistun demon linkki valmiiseen luonnokseen tarjouskohtaan ilman AI-kutsua (`{body}` → `{body, demo_url}`), 409 jos ei julkaistua demoa tai DNC |
| POST | `/send-email` | Lähetä sähköposti SMTP:llä (`to`, `subject`, `body`, valinnainen `lead_id`). 409 jos `lead_id`:n liidi tai vastaanottajaosoite kuuluu käyttäjän do_not_contact-liidille |

## Tekniset valinnat

- **Google-haku (Places API New), mukautuva ruudukko**: Geocoding API → kaupungin viewport → yksi `POST places.googleapis.com/v1/places:searchText` koko viewportille (`locationRestriction.rectangle`, `textQuery`=toimiala, `pageSize` 20, `languageCode`/`regionCode` fi, `pageToken`-sivutus max 3 sivua). Jos alue täyttyy (60 tulosta = API:n maksimi, alueella voi olla lisää), se jaetaan 2x2 neljännekseen (`split_rectangle`, ei aukkoja/limitystä) ja vain täyttyneet neljännekset jaetaan edelleen (leveyshaku, `MAX_SPLIT_DEPTH=2` → max 1+4+16 aluetta). Deduplikaatio place id:llä → CLOSED_PERMANENTLY pois → `merge_duplicates()`: sama normalisoitu nimi (casefold, välimerkit ja ylimääräiset välit pois) JA sama puhelin (numerot, +358/00358 → 0) = yksi tulos, säilytetään se jolla enemmän arvosteluja (pelkkä nimi ei riitä, ketjuilla useita toimipisteitä; ilman puhelinta ei yhdistetä). Ei Details-kutsuja. Pieni kaupunki = 1 Geocoding + 1–3 Text Search -sivua
- **Field mask** (`PLACES_FIELD_MASK`, `X-Goog-FieldMask`-header): places.id, displayName, formattedAddress, nationalPhoneNumber, websiteUri, rating, userRatingCount, businessStatus, primaryType, googleMapsUri + nextPageToken. Field mask määrää hinnan: rating/userRatingCount/websiteUri/nationalPhoneNumber ovat **Text Search Enterprise** -kenttiä, ja koko pyyntö laskutetaan korkeimman SKU:n mukaan
- **Hinta-arvio** (Googlen hinnasto 11/2026, 0–100k-taso): Text Search Enterprise $35 / 1000 (1000 ilmaista/kk), Geocoding $5 / 1000 (10 000 ilmaista/kk). Pahin tapaus per haku = 1 Geocoding + 14 Text Search = ~$0.50. Kauniainen (parturi): vanha 3x3-grid 10 kutsua ≈ $0.32 → mukautuva 3 kutsua ≈ $0.075. Dokumentaatio ei kerro erikseen sivutuksen laskutusta — arvio olettaa jokaisen sivun omaksi pyynnökseen. Hinnat: `PRICE_PER_CALL_USD` main.py:ssä; UI näyttää listahinnan ennen ilmaiskiintiötä
- **Ei Places-sisällön välimuistia**: Googlen ehdot rajoittavat sisällön tallentamista; place id saa tallentaa pysyvästi. Places-kentät tallentuvat Lead-tauluun vain kun käyttäjä itse lisää liidin pipelineen
- **Turvakytkin**: MAX_SEARCH_CALLS=15 — ehdoton raja Geocoding + Text Search -kutsuille per haku. Laskuri on säieturvallinen (`threading.Lock`, varaus ennen kutsua)
- **Uudet liidit -haku**: `GooglePlacesService.iter_places()` on generaattori (sivu = yksi Text Search -kutsu), `collect_new_leads()` kuluttaa sivuja ja lopettaa heti kun määrä täyttyy, jolloin seuraavia kutsuja ei tehdä. Pois suljettuja (pipeline, hylätyt, nähdyt) ja suodattimiin mahtumattomia (`could_match`: esim. "ei sivua" -suodatin ja oikea sivu, tai paras mahdollinen pistemäärä alle minimin) ei analysoida. Sivuanalyysi 8 rinnakkaista per hakusivu. Frontendin aikaraja 180 s
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
  - Koodissa: mallin oma lopputervehdys/[Nimesi] poistetaan (`strip_model_sign_off`), sitten "Terveisin," + allekirjoitus profiilista + `OPT_OUT_LINE`. Allekirjoitus (`build_signature`): nimi / `brand_name` (tai `company_name`) · sivusto ilman https:// (`display_website`) / puhelin; puuttuvat osat jätetään pois ilman tyhjiä rivejä tai irtopisteitä. Subject `email_subject()`: lyhyt ja luonnollinen ("Kysymys nettisivuista", "Löysin teidät Facebookista", "Nettisivunne ei aukea", "Huomasin jotain sivuistanne", "Sivunne puhelimella", "Kysymys nettisivuistanne")
  - Laatuvahti `check_generated_text()` lokittaa WARNING-tason varoituksen (ei estä): kielletyt sanat (`FORBIDDEN_PATTERNS`: ihana, upea, mahtava, ainutlaatuinen, intohimo, ratkaisu, kokonaisvaltainen, digitaalinen läsnäolo, seuraavalle/uudelle tasolle, innovatiivinen, räätälöity, huippu-, saumaton, synergia, liiketoiminnan kasvu, keskustella tarkemmin, saattaa), yli ~110 sanaa, euromäärät
- **Demosivut** (`app/demo_site.py`, pohjat `app/templates/demo/*.html.j2`): AI ei kirjoita HTML:ää. `SITE_MODEL` (oletus `EMAIL_MODEL`) palauttaa JSONin (`DemoAIContent`: hero_title, hero_subtitle, valinnainen about_title, about, 3–6 services; `extra=forbid`, pituusrajat). `content_violations()` hylkää numerot (hinnat, vuosiluvut, määrät), €/euro/alkaen, lainausmerkit (sitaatit), arvostelut/tähdet, palkinnot, historian (perustettu, vuodesta, vuosien kokemus), asiakaskehut, kielletyt sanat, väitteet joita lähdetiedoissa ei ole (hero- ja esittelytekstit: sijainti, oma valmistus, perhe/omistajat, perinteet, koko — sallittu vain jos nimi, osoite tai Deep Scan tukee; `_UNSUPPORTED_CLAIMS`) ja keksityt nimet (iso alkukirjain lauseen keskellä, ellei sana — tai sen 5 ensimmäistä kirjainta taivutuksen takia — esiinny yrityksen nimessä, kaupungissa, osoitteessa tai Deep Scan -tekstissä). Hylkäyksestä yksi uudelleenyritys virheineen, sitten 502. `price_note` tulee koodista pohjan mukaan (oletus "Hinnat ja ajanvaraus puhelimitse.", kahvila "Hinnat tiskillä ja puhelimitse."; pohjan vaihto vaihtaa oletustekstin, käyttäjän oma säilyy), käyttäjä voi muokata. Käyttäjän PATCH-muokkaukset validoidaan vain skeemaa vasten (käyttäjä saa kirjoittaa oikean hinnan)
  - **Versio 2 -pohjat (Phase 16, portfolion esimerkkisivuista)**: `cafe` = Paahtoaste (Pikkupaahtimo: osiot tummuvat sävyistä 1–4, pyöreä kääntyvä hero, paletit paahto/kaura/ruis), `salon` = Kaislikko (Kaislaranta: hero seitsemänä suikaleena samasta kuvasta, kolme kapeaa pystykuvaa, Varaa aika -osio, paletit järvi/kanerva), `barber` = Kulmakyltti (Kulmapää: nimi kahdella seinällä `kyltti_split()`: sanan kohdalta tasaisimmin / yhdyssanan liitoksesta / varaversio ≤ 5 merkkiä tai ei jakokohtaa → nimi + Parturi (Barber jos nimessä on jo parturi); yli 16 merkin seinä → tavallinen nimiotsikko; seinä 1,25 em ettei Ä:n pisteet leikkaudu; mustavalkokuvat CSS:llä; paletit kyltti/emali). Valinta: barber → barber, hair/beauty/nail/spa/salon → salon, cafe/coffee/bakery/tea (kokonaiset sanat) → cafe, ravintolat → restaurant, muut → services. Rakenne: `base_v2.html.j2` (banneri, noindex, `#aukiolo`) + pohja; tiedostot `templates/demo/assets/{yhteinen,cafe,salon,barber}/` (tyylit.css, fontit + OFL, `yhteinen/aukiolo.js` + `demo.css`). Viittaus suhteellisesti `a/{ryhmä}/{tiedosto}?v={SHA-256:n 10 merkkiä}` (`demo_asset()`; CSS:n fonttiviittauksiin lisätään fontin ?v= automaattisesti). Ei inline-tyylejä eikä -skriptejä: paletti `<html data-paletti>`-attribuutilla, kyltin koko `data-vaaka/data-pysty`-attribuuteista, AI-otsikoiden koko rajataan pisimmän sanan mukaan (`data-pisin`, `longest_segment()`, container query -yksiköt). Osiot, joille ei ole dataa (hinnasto, lounas, kampaajat, pavut, sitaatti, kartta), on korvattu esittelyllä, palvelulistalla ja tunnelmakuvilla. Paletit testataan CSS:stä (`tests/test_demo_v2.py`, AA ≥ 4,5:1). Lighthouse mobiili 98–100 (SEO 58 = noindex)
  - Aukiolo versio 2: Place Detailsin `periods` samasta vastauksesta (sama field mask) → `opening_periods` (päiväkohtaiset jaksot, keskiyön yli jatkuva jaetaan, ilman closea = ympäri vuorokauden). `#aukiolo` data-ma…data-su (`aukiolo_attrs`), `aukiolo.js` (portfoliosta, tukee useaa jaksoa per päivä: "10:00-12:00,13:00-17:00") täyttää "Auki nyt, sulkeutuu klo X" -tilan, Tänään-yhteenveto (`hours_summary`: "Ma–pe 10–19, la 10–15, su suljettu") ja kiinteä viikkoaikataulu (`week_rows`, vanhoille demoille weekdayDescriptionsista) toimivat ilman JS:ää. Ilman aikoja tila-elementit ja skripti jäävät pois
  - Classic-pohjat (versio 1): `beauty` (hair/barber/beauty/nail/spa/salon...), `restaurant` (restaurant/cafe/bakery/bar...), `services` (muut) — valittavissa modaalissa. Kolme värimaailmaa kullekin (kontrasti ≥ WCAG AA). Yksi staattinen HTML, inline CSS, ei JavaScriptiä, semanttinen HTML, skip-link, `lang="fi"`, Jinja2 autoescape. Mobiili ensin (testattu 390 px ja 1280 px kuvakaappauksilla)
  - Ilme: hero = täysleveä Unsplash-kuva tummalla liukuvärillä (tai pohjan gradientti + SVG-koriste ilman kuvaa); yläotsikko (`hero_title`, esim. "Parturi-kampaamo Kauniaisissa") → **yrityksen nimi h1:nä** otsikkofontilla → `hero_subtitle` → Soita + Reittiohjeet. Palvelut: jokaiselle oma SVG-ikoni (`app/demo_icons.py`: avainsanat nimestä/kuvauksesta → scissors, palette, wind, leaf, razor, cup, cake, utensils, wrench, droplet, bolt...; ei toistoa samalla sivulla, varaikonit pohjan poolista). Ruudukko luokalla `services n{3-6}`: 1 sarake mobiilissa, 2 sarakkeessa pariton viimeinen kortti koko leveydelle, ≥960 px: 3→3, 4→2×2, 5→3+2, 6→3×3 — ei yksinäistä korttia. Tunnelmakuvat (2–3) galleriana (mobiilissa vaakavieritys). Aukioloajat ja yhteystiedot paneeleina. Mobiilissa kiinteä "Soita"-alapalkki (headerin soittonappi vain ≥960 px)
  - Fontit: yksi otsikkofontti per pohja, base64-upotettuna (`font_face_css`, ei CDN:ää): beauty = Cormorant Garamond 600, restaurant = DM Serif Display 400, services = Manrope 700 (Fontsource 5.3.0, latin, OFL — lisenssit `templates/demo/fonts/OFL-*.txt`). Leipäteksti system-ui. Demo n. 47–55 kt
  - Kuvat (`app/utils/unsplash.py`, `UNSPLASH_ACCESS_KEY`): haku alan englanninkielisillä avainsanoilla primary_typen mukaan (`image_queries`; ei koskaan yrityksen nimellä; Unsplashin `lang`-haku on beta joka vaatii hakemuksen), `orientation=landscape`, `content_filter=high`, max 2 hakua (toinen vain jos alle 4 tulosta). Hero (`pick_hero`): ei ihmisiä (`_PEOPLE_RE` alt/description, myös client/customer/stylist) eikä tuotteita/merkkejä (`_PRODUCTS_RE` alt/description/tags: product, brand, logo, label, shelf, bottle, cosmetics, packaging, shampoo, skincare...). Järjestys: puhdas → ihmisiä → tuotteita → molempia; jos puhdasta ei ole, käytetään parasta jäljelle jäänyttä ja lokitetaan WARNING. Rajoitus: tunnistus perustuu Unsplashin metatietoihin, ei kuvan sisältöön (esim. Tainan v2-hero näyttää merkkihyllyjä, mutta sen tagit eivät mainitse niitä) — tällöin kuva vaihdetaan modaalissa. Tunnelmakuvat valitaan samasta vaihtoehtolistasta (ihmisettömät ensin), jotta hero-vaihto pitää valinnat johdonmukaisina. Hero-liukuväri: mobiilissa alhaalta tumma, ≥960 px vasemmalta tumma (teksti vasemmalla) + tekstivarjo. Tallennetaan `content.images`: hero, mood (≤4), options (≤8). Ei kuvia Googlesta eikä yrityksen sivulta. Ilman avainta / virheessä gradientti
  - Kuvat versio 2: pohjakohtaiset haut (`_TEMPLATE_QUERIES`), kahvilassa, kampaamossa ja parturissa molemmat haut aina ja tulokset sekoitetaan (`mix_results`: hero 1. hausta, tunnelmakuvat 2.): kahvila "coffee cup from above" + "cafe pastries", kampaamo "glossy wavy hair close up" + "braided hairstyle back view" (kynsi/spa/kauneus: alan omat haut), parturi "barbershop interior" + "barber tools". `face_risk` (kasvosanat, terä + ihminen, tai enemmän ihmisiä kuin hius-/käsi-/takaa-mainintoja) korvaa has_peoplen järjestyksessä; `tool_closeup` (clipper, trimmer, shaver, brush... ilman ihmistä) vain viimeisiksi, koska merkki näkyy usein vaikka kuvaus ei kerro; `BLOCKED_PHOTO_IDS` = silmämääräisesti todetut merkit (lisää id kun huomaat). Kampaamo: frizz/static/messy pois, kuvat ilman hiussanaa viimeisiksi; kampaamo ja parturi: eläin-/turkiskuvat pois. Kahvilan yhteystieto-osion kuva on tummin ehdokas (Unsplashin keskisävy `color`, luminanssi ≤ 0,06) tai ei kuvaa. Kuvaajat kerran alatunnisteessa (nimi + profiililinkki + Unsplash)
  - Unsplash-ehdot (11/2026): hotlinking pakollinen (`photo.urls.raw` + w/q/fit/auto, ixid säilyy), attribuutio jokaisen kuvan kohdalla "Kuva: Nimi / Unsplash" linkeillä kuvaajan profiiliin ja Unsplashiin `?utm_source={UNSPLASH_APP_NAME}&utm_medium=referral` (myös UI:n pikkukuvissa), `download_location` kutsutaan (BackgroundTasks) kun kuva otetaan käyttöön (generointi + hero-vaihto), avain vain palvelimella. Demo-tila 50 pyyntöä/h (generointi ≤ 6). Ohjeissa "API is to be used for non-automated, high-quality, and authentic experiences" — siksi käyttäjä valitsee kuvan modaalissa; varmista Unsplashilta ennen production-hakemusta
  - Tekstit: arkikieli kuin alan yrittäjä puhuisi, palvelukuvaus TÄSMÄLLEEN yksi lause (≤140 merkkiä, kova tarkistus), about 2–3 lausetta ilman yrityksen nimeä, `hero_title` = yläotsikko joka ei toista yrityksen nimen sanoja (esim. "Hiukset kuntoon Kauniaisissa"). Kielletyt lisäksi: autamme, tarjoamme laadukasta, tervetuloa huolehtimaan (koskee myös sähköposteja). Toistotarkistus `text_quality.repeated_phrases()`: 2–4 sanan fraasit, joissa ≥1 sisältösana, koko sivulta (`demo_site.page_texts`: yrityksen nimi, AI-tekstit, pohjan kiinteä `services_lead`, price_note). Pehmeä sääntö: 1. kierroksella toisto → uudelleenyritys virheineen, 2. kierroksella hyväksytään + WARNING-loki
  - Kuvan vaihto: `PATCH /leads/{id}/demo` `{"hero_image_id": "<id optioista>" | "none"}` ilman AI-kutsua; tunnelmakuvat valitaan uudelleen vaihtoehdoista heroa lukuun ottamatta
  - Demomerkintä aina: ohut yksirivinen palkki ylhäällä (12 px) — leveällä näytöllä "Tämä on luonnos, jonka {lähettäjä} teki yritykselle {yritys}. Ei yrityksen virallinen sivu. · puhelin · sivusto", mobiilissa "Luonnos – ei virallinen sivu · {lähettäjä} · puhelin" (display:none-vaihto, ei toistoa ruudunlukijalle). Footerissa vain yrityksen nimi ja kaupunki. `<meta name="robots" content="noindex, nofollow">` + X-Robots-Tag. CSP versio 1: `img-src data: https://images.unsplash.com; font-src data:`; versio 2: `style-src 'self'; script-src 'self'; font-src 'self'` (banneri myös versiossa 2, `yhteinen/demo.css`)
  - Aukioloajat: yksi Place Details (New) -kutsu `GET places.googleapis.com/v1/places/{id}?languageCode=fi`, `X-Goog-FieldMask: regularOpeningHours` (Place Details Enterprise -SKU, $20/1000, 1000 ilmaista/kk) vain kun `USE_LIVE_GOOGLE=true`, avain on ja place id on oikea (ei dev-/manual-)
  - Kustannusloki per generointi: AI-tokenit (`MODEL_PRICES_PER_1M`) + Place Details + Unsplash-pyyntöjen määrä. Live v2 (Taina, gpt-6.1-terra low, oikeat Unsplash-kuvat): AI 902 in / 218 out ≈ $0.002 + Place Details $0.02 + Unsplash $0 (1 haku + 4 lataustapahtumaa; hero-vaihto +1 per uusi kuva) = ~$0.022 per demo
  - **Sähköposti demolinkillä** (julkaistu demo, `generate-email`): oma prompti `DEMO_EMAIL_SYSTEM_PROMPT`, malli kirjoittaa vain kappaleet 1–2 (≤ ~55 sanaa): (1) kuka olen + miten löysin, (2) mitä asiakkaalle tapahtuu nyt tämän ongelmatyypin kohdalla (`customer_impact()`: NO WEBSITE → löytää kartalta mutta ei näe palveluita/hintoja/aukioloja, social → vain Facebook, BROKEN → Googlen "Verkkosivusto"-linkki ei aukea / virheilmoitus / "sivua ei löydy" / väärä sivu, INSECURE → selain varoittaa / "ei turvallinen", NOT MOBILE → pieni tietokoneversio puhelimella; UNKNOWN/OK → ei väitetä ongelmaa). Koodi (`build_demo_email_body`): "Hei," + 1–2 + (3) `DEMO_LINK_PARAGRAPH` linkki omalla rivillään + "Voitte katsoa sen suoraan puhelimella", (4) `DEMO_RISK_PARAGRAPH` ilmainen, ei sido, viimeistelen teidän tiedoillanne ja kuvillanne, (5) `demo_next_step`: vastatkaa tähän tai soittakaa (puhelin profiilista, ilman sitä vain vastaus) + allekirjoitus + opt-out. `clean_demo_paragraphs` poistaa mallin tekstistä tervehdyksen, lopputervehdyksen, markdownin, URLit/paikkamerkit, luonnosmaininnat ja kaikki kysymyslauseet (ei "Mitä pidätte...?"), max 2 kappaletta. Aihe `demo_email_subject`: "Tein teille luonnoksen nettisivuista" (NO WEBSITE) / "...uusista nettisivuista". Sanamäärä ennen allekirjoitusta ~85–100 (raja 110, ylitys lokiin). Ilman julkaistua demoa vanha rakenne (`EMAIL_SYSTEM_PROMPT`)
  - Sähköposti: vain jos liidillä on **julkaistu** ja voimassa oleva demo (`get_published_demo`: status published, ei vanhentunut, R2 konfiguroitu → julkinen https-osoite, ei koskaan localhost), TARJOUS = `DEMO_LINK_SENTENCE` "Tein teille jo valmiin luonnoksen, jonka voitte katsoa täältä: [DEMO_LINKKI]". `insert_demo_link()` korvaa paikkamerkin koodissa ja poistaa mallin kirjoittamat URLit. Jos paikkamerkki puuttuu, `place_demo_link()` korvaa luonnosta koskevan lauseen (esim. "Voin tehdä teille ilmaisen luonnoksen…") linkkilauseella tai lisää linkkilauseen omaksi kappaleekseen ennen lyhyttä loppukysymystä — ei toistoa. Ilman julkaistua demoa linkkiin viittaava lause poistetaan kokonaan
  - **Demo + email -ketju**: PipelineCardin "Demo + email" → `GET /leads/{id}/demo`; 404 → generoi (`POST`, lataustila napissa), olemassa oleva demo (draft/published) avataan suoraan ilman uutta AI-kutsua. DemoModalin otsikkorivin pääpainike "Publish & create email" julkaisee (jos ei jo julkaistu) ja vasta onnistuneen julkaisun jälkeen avaa EmailDraftModalin `require_demo_link=true`:lla. Julkaisuvirhe (503 ei konfiguroitu / 502 lataus) näytetään modaalissa, eikä sähköpostia luoda. Backend: `generate-email` `require_demo_link=true` ilman julkaistua demoa → 409 ennen AI-kutsua (ei hiljaa linkitöntä luonnosta). Vastaanottaja esitäytetään liidin emaililla; jos sitä ei ole, huomautus + "Call script" -nappi. EmailDraftModal tarjoaa "Add demo link to this draft" jos julkaistu linkki puuttuu luonnoksesta: `POST /leads/{id}/email/demo-link {body}` → linkki tarjouskohtaan ilman AI-kutsua (409 jos ei julkaistua demoa tai DNC). do_not_contact estää koko ketjun (409 demo/publish/email/demo-link/call-script, nappi disabloitu). Virheviestit `src/lib/apiErrors.ts` (409 erotellaan detailin perusteella)
  - **Julkaisu (Phase 13b, Cloudflare R2 + Worker)**: `app/demo_publish.py` lataa HTML:n R2:een S3-API:lla (boto3, `region=auto`, checksumit `when_required`) avaimella `demos/{polku}.html` (polku = `demo_path()`: slug, tai token ennen slugeja luoduilla demoilla), metadata `expires-at`, `Cache-Control: no-store`. Worker (`worker/src/index.ts`, R2-binding `DEMOS`) palvelee `GET /{polku}` samoilla suojaheadereilla (+ `frame-ancestors 'none'`), polku = slug (`SLUG_RE`, sama regex kuin backendissä, testi vertaa) tai 43-merkkinen token; 404 tuntematon/väärän muotoinen polku (ei R2-hakua), 410 jos `expires-at` mennyt, `robots.txt` Disallow kaikki. Julkinen linkki = `{DEMO_PUBLIC_BASE_URL}/{polku}` → oma domain vaihtuu pelkällä env-muutoksella + domainin kytkennällä Workeriin Cloudflaressa
  - **Version 2 tiedostot R2:ssa**: `publish_html(..., assets)` lataa ensin pohjan tiedostot avaimella `assets/{ryhmä}/{tiiviste}/{tiedosto}` (vain jos puuttuu: `exists` + prosessin muisti, `Cache-Control: immutable`), sitten HTML:n metadatalla `format: 2`. Tiedostoja ei poisteta: jo lähetetty demo viittaa aina omaan versioonsa. Worker: `GET /a/{ryhmä}/{tiedosto}?v={tiiviste}` → avain (regexit samat kuin backendissä, testi vertaa), Content-Type päätteestä, immutable, `Access-Control-Allow-Origin: *`; HTML:n CSP valitaan `format`-metadatasta (vanhat demot ennallaan). Workerin uusi versio pitää deployata ennen ensimmäistä version 2 julkaisua
  - **Luettavat osoitteet** (`demo_site.name_slug` / `new_public_slug`): nimestä pienet kirjaimet, ä/å→a, ö→o, aksentit pois, välimerkit väliviivoiksi, yritysmuodot (oy, ab, ky, tmi…) pois aina, yleiset toimialasanat (parturi, kampaamo, ravintola…) pois jos nimi yli 24 merkkiä (ellei jäljelle jää mitään), katkaisu sanarajalla 40 merkkiin; tyhjä → `demo`. Satunnaisosa 5 merkkiä aakkostosta ilman 0/o/1/l/i (`secrets.choice`, 31^5 ≈ 28,6 milj. per nimi). Törmäys: kannasta tarkistus (slug- ja token-sarakkeet, sama polkunimiavaruus) ja uusi satunnaisosa, max 10 yritystä; rinnakkainen luonti → unique-indeksi + yksi uusi yritys. Listausta ei ole: R2-bucket ei julkinen, Worker ja `/demo/` palvelevat vain tarkan polun, robots.txt Disallow, noindex. Vanhat demot (public_slug None) pitävät token-osoitteensa, joten jo lähetetyt linkit ja R2-objektit eivät muutu
  - Julkaisun tilat: `POST /leads/{id}/demo/publish` (409 DNC, 428 profiili, 503 ei konfiguroitu, 502 lataus epäonnistui → pysyy draftina) renderöi tuoreena ja asettaa `published`, `published_at`, `expires_at = +DEMO_TTL_DAYS` (30). `POST .../unpublish` poistaa R2:sta (502 jos poisto epäonnistuu) → draft. PATCH ja uudelleengenerointi päivittävät julkaistun version samaan osoitteeseen (lataus ennen committia). Demon ja liidin poisto poistaa myös R2-objektin (best effort)
  - Vanheneminen: `run_demo_expiry()` lifespanin taustatehtävänä (60 s käynnistyksestä, sitten `DEMO_EXPIRY_INTERVAL_SECONDS`, oletus 6 h, vain jos R2 konfiguroitu): vanhentunut + liidi Hired → jatketaan 30 pv (uusi `expires-at` R2:een); muut → poisto R2:sta + `expired`. Jos R2-poisto epäonnistuu, Worker palauttaa silti 410 metadatan perusteella
  - `DemoOut`: `preview_url` (backendin `/demo/{token}`, lasketaan pyynnön osoitteesta), `public_url` (vain julkaistulle), `publishing_enabled`. UI: Publish (30 days) / Unpublish, julkinen linkki + kopioi, voimassaolopäivä
  - UI: PipelineCardin "Generate demo" → DemoModal: pohjan valinta ennen generointia, iframe-esikatselu (`sandbox="allow-scripts"` ilman allow-same-origin: aukiolo.js toimii, eristys säilyy), automaattinen 390 px puhelinkuvakaappaus vieressä (päivittyy jokaisen muutoksen jälkeen; 501 → skaalattu 390 px iframe), pohja- ja värivalinta (PATCH heti), tekstien muokkaus (3–6 palvelua), Save texts, Open in new tab, Regenerate (vahvistus), Delete
- **Puhelinskripti** (`CALL_SCRIPT_SYSTEM_PROMPT`): sama malli, profiili ja havainto; rakenne 1. Avaus (nimi + esittely + "Onko teillä hetki, vai soitanko myöhemmin?") → 2. Havainto (yksi arkikielinen lause) → 3. Tarjous + yksi suora kysymys (ei konsulttimaisia kysymyksiä) → 4. Jos "ei kiinnosta": täsmälleen "Selvä, kiitos ajastanne, mukavaa päivää!" → 5. Jos kysyvät hintaa: riippuu tarpeesta + ehdota luonnosta/tapaamista, ei euromääriä. Ei scrapingia eikä Deep Scan -sisältöä. Prompti: pelkkä teksti numeroiduilla riveillä; `strip_markdown()` poistaa koodissa #-otsikot, lihavoinnit ja luettelomerkit. Sähköposti- ja skriptiprompti kieltävät yrityksen pitkän virallisen nimen avauksessa (lyhyt muoto, "teidän kampaamonne" tai ei nimeä)
- **Do not contact**: `Lead.do_not_contact` estää generate-email, generate-call-script ja send-email (409). UI: "Mark do not contact" / "Allow contact again" PipelineCardissa, AI Draft ja Call script disabloitu
- **Yhteystietohaku** (`app/utils/contact_finder.py`, `find_contact_email(website) -> ContactEmail(email, source) | None`): `website_check.fetch_page()` samoilla UA/timeout/retry/SSL-säännöillä kuin sivuanalyysi. Etusivu + max 3 samalla sivustolla olevaa linkkiä, joiden teksti tai polku sisältää `CONTACT_KEYWORDS` (yhteystiedot, ota-yhteytta, contact, kontakt...). Ei muuta crawlausta. Poimii mailto-linkit, tekstin, peitetyt muodot (`(at)`, `[at]`, `{at}`, `(ät)`, `(dot)`, `(piste)`) ja Cloudflare Email Protectionin. Scriptit/style ohitetaan; kuvatiedostonimet, esimerkkiosoitteet (example.*, domain.fi, nimi@...), noreply ja sentry/wixpress pois. Järjestys: oma domain > yleinen osoite (`GENERIC_LOCAL_PARTS`: info, asiakaspalvelu, myynti...) > löytöjärjestys. Ei arvailua eikä ulkoisia palveluita. Ajetaan aina taustasäikeessä (`asyncio.to_thread`); POST /leads käyttää `BackgroundTasks`:ia, jotta tallennus ei odota (pahimmillaan 4 sivua × 8 s × 2)
- **SMTP-lähetys**: Suora sähköpostin lähetys EmailDraftModalista, konfiguroidaan .env:ssä. `app/utils/smtp_client.py`: portti 465 = `SMTP_SSL`, muut = `SMTP` + EHLO + STARTTLS + EHLO + login, varmennettu TLS (certifi), timeout 20 s, EHLO-nimenä IP-literaali jos `getfqdn()` antaa `.arpa`/`.local`-nimen, viestissä Date + Message-ID. Virheet luokitellaan (`SmtpFailure`: connection / tls / auth / send + vaihe) → `/send-email` palauttaa 502 turvallisella viestillä (ei tunnuksia), UI näyttää tyypin ja vihjeen. iCloud: `smtp.mail.me.com:587`, SMTP_USER = koko iCloud-osoite, sovelluskohtainen salasana, SMTP_FROM = sama osoite tai sen alias
- **SMTP-diagnostiikka**: `cd backend && python scripts/smtp_check.py [--quiet] [--send-test]` — yhdistää ja kirjautuu vaiheittain (debug-tuloste, AUTH-vaihe piilotettu, osoitteet maskattu), kertoo missä vaiheessa katkeaa. Ei lähetä mitään ilman `--send-test`-lippua, silloinkin vain osoitteeseen SMTP_FROM
- **Pipeline-navigointi**: Chevron-napit (< >) dropdownin sijaan, yhden klikkauksen stage-siirto
- **Bulk Actions**: Leijuva toolbar — Move Stage, AI Drafts, CSV Export, Delete valituille liideille (erissä, 5 kerrallaan)
- **Deep Scan**: Verkkosivun leipätekstin scraping (requests + BeautifulSoup, 5s timeout) → teksti cachetetaan Lead.website_context -kenttään → OpenAI käyttää sitä personoitujen jäänmurtajien generointiin sähköposteihin. Vikasietoinen: jos scraping epäonnistuu, meili generoidaan ilman personointia. Osittain toimiville sivuille (alla) käytetään laajennettua skannausta, joka täyttää myös website_contextin
- **Laajennettu Deep Scan** (`app/utils/site_content.py`, BROKEN WEBSITE joka vastaa silti HTML:llä, INSECURE, NOT MOBILE; ei parkkisivuja eikä DNS-virheitä): etusivu + enintään 3 alasivua samalta sivustolta, yksi per luokka (hinnasto, palvelut, meistä; avainsanat polusta tai linkkitekstistä). **robots.txt** (`AgencyHunter`): estetty sivu jätetään hakematta, estetty etusivu = ei skannausta; robots.txt 401/403/5xx/ei vastausta = ei hakuja, 404 = kaikki sallittu. **Viive** 1 s pyyntöjen välillä (tai Crawl-delay, max 5 s). Kuvia ei poimita (img/picture/source/figure poistetaan ennen tekstiä). Yksi AI-kutsu (`SITE_FACTS_SYSTEM_PROMPT`, EMAIL_MODEL) → `{services: [{name, price}], about}`, jonka `verify_site_facts` tarkistaa: palvelun nimi löytyy sivujen tekstistä, hinnan luvut ja valuutta samalla sivulla enintään 160 merkin päässä nimestä, esittelyn sanoista ≥ 75 % sivuilta. Tallennus `Lead.website_facts` kerran per liidi (demo ja sähköposti käyttävät samaa)
- **Hinnat demossa**: malli ei koskaan kirjoita hintoja (`DemoAIService` ilman hintakenttää, `extra=forbid`, € ja numerot hylätään). Promptissa palvelut nimillä ilman hintoja, ja `attach_site_prices` liittää hinnan koodissa vain samalle nimelle (tai yksiselitteinen osittainen osuma). Kun hinta näkyy: merkintä "Hinnat nykyiseltä sivultanne." huomautusrivillä, price_note pohjan `price_note_site` ("Ajanvaraus puhelimitse." / "Kysykää myös muista palveluista." / kahvila "…tuotteista."). Modaalissa hinnan voi poistaa, ei kirjoittaa: PATCH hyväksyy vain `website_facts`issa olevat hinnat (422). `DemoStoredContent.site_based` → demosähköpostin linkkikappale "Tein luonnoksen nykyisten tietojenne pohjalta, …" (`DEMO_LINK_PARAGRAPH_SITE`)
- **Auth**: Supabase Auth + JWT. Frontend käyttää `@supabase/supabase-js`, session tallentuu selaimeen, access_token lisätään automaattisesti `apiFetch`-helperillä Authorization-headeriin. Backend verifioi JWT:n (`backend/app/auth.py`, `verify_token`-dependency) tukien sekä uusia ES256/RS256-tokeneita JWKS-endpointista (`PyJWKClient`, `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, avainten cache, macOS-venvissä certifi-SSL-context) että legacy-HS256-tokeneita `SUPABASE_JWT_SECRET`-salaisuudella. Algoritmi tunnistetaan tokenin headerista. `AUTH_DISABLED=true` ohittaa verifioinnin dev-kehityksessä. SidebarNav näyttää kirjautuneen käyttäjän emailin ja sign-out-napin
- **Multi-tenancy**: Lead, EmailDraft ja SearchHistoryEntry sisältävät `user_id`-kentän (Supabase UUID, indexed). Kaikki endpointit suodattavat `user_id == current_user.id`: GET-listat `.where(user_id)`, PATCH/DELETE/single-GET palauttavat 404:n (ei 403:a) jos toisen käyttäjän resurssia yritetään käyttää — ei paljasta resurssien olemassaoloa. POST-operaatiot asettavat `user_id` serverissä `AuthUser.id`:stä (ei clientin syötteestä). `Lead.google_place_id` ei ole enää globaalisti unique — `UniqueConstraint("google_place_id", "user_id")` sallii saman yrityksen useammalle käyttäjälle.
- **Aikaleimat**: Kaikki datetime-kentät luodaan aikavyöhykkeellisinä (`models.utc_now()` = `datetime.now(timezone.utc)`). Uudet SQLModel-versiot hylkäävät naive-datetimet. Älä käytä `datetime.utcnow()`:ia
- **Käynnistys**: FastAPI:n `lifespan`-handler kutsuu `create_db_and_tables()`, joka ajaa `create_all`:n vain dev-SQLitessä
- **Migraatiot (Alembic)**: `backend/alembic.ini` + `backend/migrations/` (`render_as_batch=True` SQLiteä varten, URL `app.database.engine`:stä eli `DATABASE_URL`:sta). Postgresissa skeema vain `alembic upgrade head`:lla. Ketju: `5c3252fb0873` alkuskeema → `a37cda0e085d` ScannedPlace pois → `ab965e378f8b` Lead Places-kentät + lead_score → `b128a7a9e0bd` datetime-sarakkeet TIMESTAMPTZ:ksi (vain Postgres, vain naiivit sarakkeet; SQLite no-op) → `11b71478b845` Lead.website_issue → `af5c0e76b864` Lead.email, email_source, do_not_contact (server_default false olemassa oleville riveille) → `e0c769279b9e` SenderProfile-taulu → `2390d5681096` Demo-taulu → `9148408efe32` Demo.public_slug → `3d717a6775b2` SenderProfile.brand_name. `tests/test_migrations.py` ajaa upgrade + `alembic check` + downgrade/upgrade-kierroksen, joten unohtunut migraatio kaataa CI:n
- **Olemassa oleva Supabase-kanta** (luotu `create_all`:lla ennen Alembicia): aja kerran `alembic stamp 5c3252fb0873`, sitten `alembic upgrade head`, sitten `alembic check`. Vanhat taulut luotiin `timestamp without time zone` -sarakkeilla; migraatio `b128a7a9e0bd` muuntaa ne `timestamptz`:ksi (`USING col AT TIME ZONE 'UTC'`, arvot olivat naiiveja UTC-aikoja). Migraatio tarkistaa `information_schema`:sta ja muuntaa vain naiivit sarakkeet, koska jo-tz-sarakkeille sama USING siirtäisi arvoja session aikavyöhykkeen verran. Downgrade palauttaa `timestamp without time zone`
- **Postgres-ajuri**: psycopg (v3). `normalize_database_url()` muuttaa `postgres://` ja `postgresql://` muotoon `postgresql+psycopg://`. `engine_options()` antaa Postgresille `connect_args={"prepare_threshold": None}`: Supabasen transaction pooler (portti 6543) ei tue prepared statementeja, joita psycopg3 muuten alkaa käyttää 5. toistetun kyselyn jälkeen
- **Postgres-migraatiotestit**: `TEST_POSTGRES_URL=postgresql://... pytest tests/test_migrations.py` ajaa legacy-kanta-simulaation (naiivit sarakkeet, session TZ Europe/Helsinki) ja tuoreen kannan tarkistuksen. Ilman muuttujaa testit ohitetaan (CI). **Testit tyhjentävät `public`-skeeman — älä koskaan osoita niitä Supabaseen**, vain paikalliseen kertakäyttökantaan (esim. `docker run --rm -e POSTGRES_PASSWORD=test -p 127.0.0.1:55432:5432 postgres:15`)
- **Riippuvuudet**: `backend/requirements.txt` lukittu tarkkoihin versioihin (`==`), testattu Python 3.13:lla puhtaassa venvissä. Päivitä versioita tietoisesti, ei automaattisesti
- **Testit**: pytest + FastAPI TestClient (`backend/tests/`, dev-riippuvuudet `backend/requirements-dev.txt`). `conftest.py` asettaa env-muuttujat ennen app-importtia (ei `backend/.env`:n oikeita avaimia/kantaa), käyttää in-memory SQLiteä (StaticPool) ja `dependency_overrides`-mekanismia `get_session`- ja `verify_token`-dependencyille. Käyttäjä valitaan `X-Test-User`-headerilla (`client_a` / `client_b` -fixturet) tenant-isolaation testaamiseen. Autouse-fixture estää oikeat kutsut (requests, OpenAI, scraping, SMTP); testit mockaavat tarvitsemansa
- **CI**: GitHub Actions (`.github/workflows/ci.yml`) push- ja pull_request-eventeillä: backend (Python 3.13, pytest) ja frontend (Node 22, `npm ci` + lint + build). Ei API-avaimia
- **UI hakutuloksille**: LeadTable — score (numero + ohut pistepalkki; 75+ vihreä, 50+ lime, 25+ keltainen, muuten harmaa), rating + arvostelumäärä, Google Maps -linkki, "Temporarily closed" -merkintä, "In pipeline" jo tallennetuille (Save-nappi piilossa), `website_issue` status-badgen alla. Oletusjärjestys score desc, sarakkeet Score/Business/Rating/Status klikattavia (Status: NO WEBSITE > BROKEN > INSECURE > NOT MOBILE > UNKNOWN > OK). Hakutulosten yläpuolella "N API calls, ~$X" (mock: "Mock data, 0 API calls"). PipelineCard näyttää scoren, ratingin ja issuen. Dashboardin "opportunity"-luku ei laske UNKNOWN-tilaa
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
SITE_MODEL=                    # demosivujen sisältö, tyhjä = EMAIL_MODEL
SITE_REASONING_EFFORT=         # tyhjä = EMAIL_REASONING_EFFORT
DEMO_PUBLIC_BASE_URL=          # julkaistujen demojen osoite, https (Worker workers.dev tai oma domain)
R2_ACCOUNT_ID=                 # Cloudflare-tilin ID
R2_ACCESS_KEY_ID=              # R2 API -token (Object Read & Write, vain demo-bucket)
R2_SECRET_ACCESS_KEY=
R2_BUCKET=agency-hunter-demos
DEMO_TTL_DAYS=30
UNSPLASH_ACCESS_KEY=           # demosivujen kuvat, tyhjä = gradientti
UNSPLASH_APP_NAME=agency_hunter   # attribuutiolinkkien utm_source
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

## Ulkoasu ja design tokenit

- Tumma teema ("Mono"): neutraalit harmaat, aksentti lähes valkoinen (`accent`, teksti `accent-fg`), ohuet reunat, varjo vain kelluville pinnoille (`shadow-overlay`, `shadow-popover`)
- Tokenit CSS-muuttujina `src/index.css` (`:root`, RGB-kanavat) → semanttiset nimet `tailwind.config.js`:ssä. Komponentit käyttävät vain näitä (ei `slate-*`/`indigo-*` tms.):
  - Pinnat: `canvas` (sivu), `surface` (paneelit, kortit), `subtle` (hover), `raised` (sekundaarinapit, chipit); reunat `line`, `line-strong`
  - Teksti: `fg`, `fg-muted`, `fg-subtle` (kaikki ≥ 4.5:1 jokaisella pinnalla)
  - Merkitykselliset: `score-hot/good/fair/low`, `status-none/broken/insecure/mobile/unknown/ok`, `success`, `danger`, `warning` (taustat opacity-modifierilla, esim. `bg-danger/10`)
  - Koot: `h-control` (32 px), `h-control-sm` (28 px), `p-card`, `px-cell-x`/`py-cell-y`, `px-page-x`/`py-page-y`; pyöristykset `rounded-sm` 4, `rounded` 6, `rounded-lg` 8 (isommat poistettu asteikosta)
- Fokus: globaali `:focus-visible`-rengas (`--color-focus`); kentissä reuna + 1 px outline
- Linkit: sama väri kuin teksti, hillitty alleviivaus joka vahvistuu hoverilla

## Tiedostorakenne (avaintiedostot)

```
backend/app/main.py            — GooglePlacesService, email/SMTP service, kaikki endpointit
backend/app/models.py          — Lead, LeadCreate, LeadUpdate, SearchHistoryEntry, EmailDraft
backend/app/scoring.py         — lead_score(): liidin pisteytys 0-100, painot vakioina
backend/app/text_quality.py    — Kielletyt sanat (FORBIDDEN_PATTERNS), PRICE_RE, word_count — sähköpostit, skriptit, demot
backend/app/demo_site.py       — Demosivut: sisältöskeema + validointi, pohjat/värit, Place Details -aukioloajat, renderöinti
backend/app/templates/demo/    — Jinja2-pohjat: base_v2.html.j2 + cafe/salon/barber, assets/ (CSS, aukiolo.js, fontit + OFL); Classic: base.html.j2 + beauty/restaurant/services, fonts/
backend/scripts/demo_check.py  — Demopohjien laatuportti: 6 mock-demoa, Chromium + WebKit 320–1440 px, ilman JS:ää, kuva-arkki (--serve Lighthousea varten)
backend/app/demo_icons.py      — Palveluiden SVG-ikonit ja avainsanasäännöt
backend/app/utils/unsplash.py  — Unsplash-haku, kuvien valinta, attribuutio, download tracking
backend/app/demo_publish.py    — R2-julkaisu (boto3 S3 API): publish/unpublish, konfiguraatio
worker/                        — Cloudflare Worker: src/index.ts (demojen jakelu R2:sta), wrangler.toml, test/
backend/alembic.ini, backend/migrations/ — Alembic-migraatiot (versions/)
backend/app/database.py        — DB-yhteys (SQLite dev, Postgres tuotannossa)
backend/app/auth.py            — Supabase JWT -verifiointi (ES256/RS256 JWKS + HS256 legacy, verify_token FastAPI-dependency)
backend/app/utils/scraper.py   — Deep Scan: verkkosivun leipätekstin scraping (5s timeout, max 2000 merkkiä)
backend/app/utils/site_content.py — Laajennettu Deep Scan: robots.txt, viive, max 3 alasivua, SiteFacts + tarkistus
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
src/components/DemoModal.tsx   — Demosivun generointi, esikatselu, pohja/värit, tekstien muokkaus
src/components/LeadTable.tsx    — Hakutulosten taulukko (järjestettävät sarakkeet, score, rating, Maps, In pipeline, website_issue)
src/components/ScoreBadge.tsx   — ScoreBadge (numero + pistepalkki), RatingDisplay, StatusBadge (LeadTable, PipelineCard, Dashboard)
src/types/agency.ts            — SearchResponse, SearchUsage, SearchResult, Agency, SavedAgency, WebsiteStatus, BusinessStatus, PipelineStatus, NavTab
```
