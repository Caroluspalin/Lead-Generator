"""Demopohjien (versio 2) laatuportti: mock-demot, selaintestit ja kuvakaappaukset.

Käyttö (backend/-kansiosta, venv aktiivisena, Playwright asennettuna: requirements-screenshot.txt):
  python scripts/demo_check.py --out /polku/tuloksiin              # kaikki v2-pohjat
  python scripts/demo_check.py --out /polku --template cafe         # yksi pohja
  python scripts/demo_check.py --out /polku --serve                 # jättää palvelimen käyntiin (Lighthouse)

Jokaisesta pohjasta tehdään kaksi demoa: lyhyt nimi aukioloajoilla ja pitkä nimi ilman niitä.
Tekstit ovat käsin kirjoitettuja, ja ne ajetaan samojen sisältötarkistusten läpi kuin AI:n tekstit.
Kuvat haetaan Unsplashista kerran per pohja ja tallennetaan out/kuvat-{pohja}.json, joten seuraavat
ajot eivät kuluta API-kiintiötä. Palvelin jäljittelee Workeria: /{polku} ja /a/{ryhmä}/{tiedosto}?v=,
samat CSP-headerit. Tarkistukset Chromiumilla ja WebKitillä leveyksillä 320–1440 px:
vaakavieritys, katkenneet sanat otsikoissa, konsolivirheet (myös CSP), toiminta ilman JS:ää
ja prefers-reduced-motion. Lopuksi out/arkki.png: kuvakaappaukset rinnakkain.

Premium-pohjan hero tarkistetaan lisäksi liike päällä (390 ja 1440 px): ruutusarja piirtyy ja vaihtuu
vierittäessä, Varaa aika / Soita näkyy ilman vieritystä (puhelimella ensimmäisen napin alareuna enintään
640 px:ssä, jotta se näkyy myös Safarin palkkien kanssa), yläpalkin nimi ei katkea, nappien ja tietorivin
väliin ei jää tyhjää, ja tekstin kontrasti mitataan kuvakaappauksesta kuvan päältä (AA 4,5:1). Tuloste kertoo
kirkkaimman taustan tekstin alla: se on tyylit.css:n --valossa.
"""
import argparse
import base64
import http.server
import json
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from app.demo_site import (  # noqa: E402
    DemoBusiness,
    DemoContent,
    DemoImages,
    DemoSender,
    DemoStoredContent,
    DemoTimma,
    OpeningPeriod,
    PriceCategory,
    PriceItem,
    TEMPLATES,
    content_violations,
    demo_asset,
    find_repeated_phrases,
    price_note_for,
    render_demo_html,
)
from app.utils import unsplash  # noqa: E402

CSP_V2 = (
    "default-src 'none'; style-src 'self'; script-src 'self'; font-src 'self'; "
    "img-src 'self' data: https://images.unsplash.com https://scaled-images.timma.fi; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
WIDTHS = [320, 360, 375, 390, 414, 768, 1024, 1280, 1440]
# Kiinteä testihetki: tiistai klo 12 (aukiolo.js lukee ?aika=)
TEST_TIME = "2026-11-10T12:00"
# 390 × 844 -puhelimella Safarin palkit vievät ruudusta noin 180 px: heron ensimmäisen napin pitää mahtua tähän
PHONE_CTA_MAX = 640


def _periods(spec: dict[int, list[tuple[str, str]]]) -> list[OpeningPeriod]:
    return [OpeningPeriod(day=d, open=o, close=c) for d, ranges in spec.items() for o, c in ranges]


WEEKDAYS = [1, 2, 3, 4, 5]


@dataclass(frozen=True)
class Sample:
    slug: str
    template: str
    palette: str
    name: str
    city: str
    address: Optional[str]
    phone: Optional[str]
    primary_type: str
    content: dict[str, Any]
    periods: list[OpeningPeriod]
    hero_index: int = 0  # eri hero samalle pohjalle, jotta kaksi demoa eivät näytä samalta
    timma: Optional[DemoTimma] = None  # Timma-sivun hinnasto, arvio ja varauslinkki (kuvat silti Unsplashista)


def _hinnasto(spec: dict[str, list[tuple[str, str, str, Optional[str]]]]) -> list[PriceCategory]:
    return [
        PriceCategory(name=name, items=[PriceItem(name=n, price=p, duration=d, description=k) for n, p, d, k in items])
        for name, items in spec.items()
    ]


SAMPLES: list[Sample] = [
    Sample(
        slug="kuppi-a2b3c", template="cafe", palette="paahto", name="Kuppi", city="Espoo",
        address="Esimerkkikatu 12, 02100 Espoo, Suomi", phone="040 000 0000", primary_type="cafe",
        content={
            "hero_title": "Kahvia ja pullaa joka arkiaamu",
            "hero_subtitle": "Suodatinkahvia, espressojuomia ja tuoreita leivonnaisia.",
            "about_title": "Kahvila Espoossa",
            "about": "Kahvi keitetään tilauksesta, ja leivonnaiset ovat esillä tiskillä. Pöytään voi istahtaa, ja kaiken saa myös mukaan.",
            "services": [
                {"name": "Kahvit", "description": "Suodatinkahvi, espresso ja maitokahvit, myös kaurajuomalla."},
                {"name": "Leivonnaiset", "description": "Korvapuustit, piirakat ja kakkupalat tiskiltä."},
                {"name": "Suolaiset", "description": "Täytetyt sämpylät ja piiraat lounasaikaan."},
                {"name": "Teet", "description": "Mustat, vihreät ja yrttiteet irtoteenä."},
            ],
        },
        periods=_periods({**{d: [("07:30", "17:00")] for d in WEEKDAYS}, 6: [("09:00", "16:00")]}),
    ),
    Sample(
        slug="vanha-postitalo-d4e5f", template="cafe", palette="ruis", name="Kahvila ja leipomo Vanha Postitalo",
        city="Porvoo", address="Esimerkkikatu 4, 06100 Porvoo, Suomi", phone="050 000 0000", primary_type="bakery",
        content={
            "hero_title": "Tuoretta leipää ja hyvää kahvia",
            "hero_subtitle": "Ruisleipää, pullaa ja kakkuja omasta leipomosta.",
            "about_title": "Leipomo ja kahvila samassa talossa",
            "about": "Leivomme aamuisin ja myymme päivän tuotteet tiskiltä. Kahvilan puolella voi istua alas, ja juhlakakun voi tilata etukäteen.",
            "services": [
                {"name": "Leivät", "description": "Ruisleipää, limppua ja vaaleita leipiä tiskiltä."},
                {"name": "Pullat ja piirakat", "description": "Voisilmäpullat, korvapuustit ja marjapiirakat.", "price": "alk. 3,50 €"},
                {"name": "Täytekakut", "description": "Kakut juhliin tilauksesta, kysykää vaihtoehtoja.", "price": "alk. 45 €/kg"},
                {"name": "Kahvila", "description": "Kahvit ja teet leivonnaisten kanssa paikan päällä."},
                {"name": "Lahjakortit", "description": "Lahjakortin saa kassalta mihin tahansa summaan."},
            ],
        },
        periods=[],
        hero_index=1,
    ),
    Sample(
        slug="saga-g6h7j", template="salon", palette="jarvi", name="Saga", city="Helsinki",
        address="Esimerkkitie 3, 00100 Helsinki, Suomi", phone="050 000 0000", primary_type="hair_salon",
        content={
            "hero_title": "Hiukset kuntoon Helsingissä",
            "hero_subtitle": "Leikkaukset, värit ja kampaukset naisille, miehille ja lapsille.",
            "about_title": "Kampaamopalvelut ajanvarauksella",
            "about": "Kertokaa toiveenne, niin suunnitellaan sopiva malli yhdessä. Kysykää myös hoitoa omille hiuksillenne.",
            "services": [
                {"name": "Leikkaukset", "description": "Naisten, miesten ja lasten hiustenleikkaukset."},
                {"name": "Värjäykset", "description": "Kestovärit, raidat ja sävytykset."},
                {"name": "Juhlakampaukset", "description": "Kampaukset häihin ja muihin tilaisuuksiin."},
                {"name": "Hoidot", "description": "Tehohoidot kuiville ja käsitellyille hiuksille."},
            ],
        },
        periods=_periods({**{d: [("10:00", "19:00")] for d in [2, 3, 4, 5]}, 6: [("09:00", "15:00")]}),
    ),
    Sample(
        slug="hopeapaju-k8m9n", template="salon", palette="kanerva", name="Kampaamo Hopeapaju & Kumppanit",
        city="Tampere", address="Esimerkkikatu 21, 33100 Tampere, Suomi", phone="040 000 0000",
        primary_type="beauty_salon",
        content={
            "hero_title": "Hiukset ja kauneus Tampereella",
            "hero_subtitle": "Hiukset, kulmat ja ripset samalla käynnillä.",
            "about_title": "Hiuksista kulmiin",
            "about": "Palvelemme ajanvarauksella. Kertokaa toiveistanne, niin valitaan yhdessä teille sopiva palvelu.",
            "services": [
                {"name": "Leikkaus", "description": "Leikkaus ja föönaus toiveidenne mukaan.", "price": "alk. 59 €"},
                {"name": "Värjäys", "description": "Kestovärit, raidat ja sävytykset.", "price": "alk. 120 €"},
                {"name": "Kampaukset", "description": "Juhla- ja hääkampaukset tilaisuuksiin."},
                {"name": "Kulmien muotoilu", "description": "Muotoilu ja värjäys kulmille sekä ripsille.", "price": "28 €"},
                {"name": "Hiushoidot", "description": "Tehohoidot kuiville hiuksille."},
            ],
        },
        periods=[],
        hero_index=1,
    ),
    Sample(
        slug="assa-p2q3r", template="barber", palette="kyltti", name="Ässä", city="Kuopio",
        address="Esimerkkikatu 7, 70100 Kuopio, Suomi", phone="040 000 0000", primary_type="barber_shop",
        content={
            "hero_title": "Hiukset ja parta kuntoon",
            "hero_subtitle": "Hiustenleikkaukset, koneajot ja partatyöt.",
            "about_title": "Parturi Kuopiossa",
            "about": "Kertokaa toiveenne, niin leikkaus tehdään niiden mukaan. Ajan voi varata soittamalla.",
            "services": [
                {"name": "Hiustenleikkaus", "description": "Leikkaus saksilla tai koneella."},
                {"name": "Koneajo", "description": "Tasainen koneajo tai häivytys."},
                {"name": "Parran muotoilu", "description": "Parran siistiminen ja ääriviivat."},
                {"name": "Lasten leikkaus", "description": "Leikkaukset myös lapsille."},
            ],
        },
        periods=_periods({**{d: [("10:00", "19:00")] for d in WEEKDAYS}, 6: [("10:00", "15:00")]}),
    ),
    Sample(
        slug="herrasmiesten-s4t5u", template="barber", palette="emali", name="Herrasmiesten Parturi",
        city="Oulu", address="Esimerkkikatu 15, 90100 Oulu, Suomi", phone="050 000 0000", primary_type="barber_shop",
        content={
            "hero_title": "Leikkaukset ja parranajot Oulussa",
            "hero_subtitle": "Leikkaus, parta ja kuumapyyhe samalla käynnillä.",
            "about_title": "Parturi Oulussa",
            "about": "Hiukset leikataan toiveiden mukaan, ja partaan saa muotoilun tai ajon. Kysykää vapaita aikoja puhelimitse.",
            "services": [
                {"name": "Hiustenleikkaus", "description": "Saksi- ja koneleikkaukset.", "price": "32 €"},
                {"name": "Parranajo", "description": "Parranajo kuumapyyhkeellä.", "price": "alk. 25 €"},
                {"name": "Parran muotoilu", "description": "Ääriviivat ja tasaus koneella."},
                {"name": "Kulmat ja korvat", "description": "Siistiminen leikkauksen yhteydessä.", "price": "8 €"},
            ],
        },
        periods=[],
        hero_index=1,
    ),
    # Premium: lyhyt nimi + Timma (12 palvelua, arvio, varauslinkki), pitkä nimi ilman aukioloja ja
    # hinnat omalta sivulta, sekä keskipitkä nimi ilman hintoja (kuusi AI-palvelua)
    Sample(
        slug="tera-v6w7x", template="premium", palette="messinki", name="Terä", city="Kuopio",
        address="Esimerkkikatu 7, 70100 Kuopio, Suomi", phone="040 000 0000", primary_type="barber_shop",
        content={
            "hero_title": "Hiukset ja parta kuntoon",
            "hero_subtitle": "Hiustenleikkaukset, koneajot ja partatyöt.",
            "about_title": "Parturi Kuopiossa",
            "about": "Kertokaa toiveenne, niin leikkaus tehdään niiden mukaan. Ajan voi varata verkossa tai soittamalla.",
            "services": [
                {"name": "Hiustenleikkaus", "description": "Leikkaus saksilla tai koneella."},
                {"name": "Koneajo", "description": "Tasainen koneajo tai häivytys."},
                {"name": "Parran muotoilu", "description": "Parran siistiminen ja ääriviivat."},
                {"name": "Lasten leikkaus", "description": "Leikkaukset myös lapsille."},
            ],
        },
        periods=_periods({**{d: [("10:00", "19:00")] for d in WEEKDAYS}, 6: [("10:00", "15:00")]}),
        timma=DemoTimma(
            booking_url="https://timma.fi/yritys/esimerkki-parturi", rating_avg=4.9, rating_count=187,
            price_list=_hinnasto({
                "Leikkaukset": [
                    ("Mallinmuutosleikkaus", "30 €", "45 min", "Hiusten leikkaus uuteen malliin tarkoittaen, että hiuksiin tehdään merkittävä muutos. Esimerkiksi pitkät hiukset leikataan lyhyeksi."),
                    ("Parturileikkaus", "25 €", "30 min", "Lyhyiden hiusten leikkaus tai siistiminen."),
                    ("Lasten hiustenleikkaus", "20 €", "30 min", None),
                    ("Koneajo", "20 €", "15 min", "Hiusten ajo koneella, koko pää samalla pituudella."),
                ],
                "Parta": [
                    ("Parran muotoilu", "20 €", "30 min", "Parran muotoilu saksilla ja veitsellä."),
                    ("Parran koneajo", "15 €", "15 min", None),
                ],
                "Muut hiuspalvelut": [("Hiustenpesu", "5 €", "15 min", None)],
                "Ihokarvojen poisto": [
                    ("Ihokarvojen poisto vahalla", "alk. 10 €", "15 min", "Kulmakarvat, nenäkarvat, korvakarvat"),
                    ("Kulmakarvojen poisto lankatekniikalla", "20 €", "30 min", None),
                ],
                "Combo": [
                    ("Hiustenleikkaus ja parran muotoilu (lyhyt parta)", "35 €", "45 min", None),
                    ("Hiustenleikkaus ja parran muotoilu (pitkä parta)", "40 €", "1 h", None),
                    ("Hiustenleikkaus ja parran koneajo", "30 €", "30 min", None),
                ],
            }),
        ),
    ),
    Sample(
        slug="kauniaisten-y8z9a", template="premium", palette="pullo", name="Parturi-Kampaamo Kauniaisten Hiuspiste",
        city="Kauniainen", address="Esimerkkikatu 15, 02700 Kauniainen, Suomi", phone="050 000 0000",
        primary_type="barber_shop",
        content={
            "hero_title": "Leikkaukset ja parranajot Kauniaisissa",
            "hero_subtitle": "Leikkaus, parta ja kuumapyyhe samalla käynnillä.",
            "about_title": "Parturi- ja kampaamopalvelut",
            "about": "Hiukset leikataan toiveiden mukaan, ja partaan saa muotoilun tai ajon. Kysykää vapaita aikoja puhelimitse.",
            "services": [
                {"name": "Hiustenleikkaus", "description": "Saksi- ja koneleikkaukset.", "price": "32 €"},
                {"name": "Parranajo", "description": "Parranajo kuumapyyhkeellä.", "price": "alk. 25 €"},
                {"name": "Parran muotoilu", "description": "Ääriviivat ja tasaus koneella."},
            ],
        },
        periods=[],
        hero_index=1,
    ),
    Sample(
        slug="herrasmiesten-b2c3d", template="premium", palette="messinki", name="Herrasmiesten Parturi",
        city="Oulu", address="Esimerkkikatu 15, 90100 Oulu, Suomi", phone="050 000 0000", primary_type="barber_shop",
        content={
            "hero_title": "Leikkaukset ja parranajot Oulussa",
            "hero_subtitle": "Leikkaus, parta ja kuumapyyhe samalla käynnillä.",
            "about_title": "Parturi Oulussa",
            "about": "Hiukset leikataan toiveiden mukaan, ja partaan saa muotoilun tai ajon. Kysykää vapaita aikoja puhelimitse.",
            "services": [
                {"name": "Hiustenleikkaus", "description": "Saksi- ja koneleikkaukset."},
                {"name": "Koneajo", "description": "Tasainen koneajo tai häivytys."},
                {"name": "Parranajo", "description": "Parranajo kuumapyyhkeellä."},
                {"name": "Parran muotoilu", "description": "Ääriviivat ja tasaus koneella."},
                {"name": "Kulmat ja korvat", "description": "Siistiminen leikkauksen yhteydessä."},
                {"name": "Lasten leikkaus", "description": "Leikkaukset myös lapsille."},
            ],
        },
        periods=_periods({**{d: [("09:00", "17:00")] for d in WEEKDAYS}}),
        hero_index=2,
    ),
]


def check_texts(sample: Sample) -> list[str]:
    has_prices = any(s.get("price") for s in sample.content["services"])
    content = DemoContent(**sample.content, price_note=price_note_for(sample.template, has_prices))
    allowed = " ".join(filter(None, [sample.name, sample.city, sample.address]))
    problems = content_violations(content, allowed_text=allowed)
    repeats = find_repeated_phrases(content, business_name=sample.name, template=sample.template)
    return problems + [f"toisto: {r}" for r in repeats]


def load_photos(template: str, primary_type: str, out: Path) -> list[unsplash.DemoPhoto]:
    cache = out / f"kuvat-{template}.json"
    if cache.exists():
        return [unsplash.DemoPhoto.model_validate(p) for p in json.loads(cache.read_text())]
    key = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
    if not key:
        print(f"  {template}: ei UNSPLASH_ACCESS_KEY:tä, demot ilman kuvia")
        return []
    photos = unsplash.find_candidates(primary_type, template, key)
    cache.write_text(json.dumps([p.model_dump() for p in photos], ensure_ascii=False, indent=1))
    return photos


def images_for(sample: Sample, photos: list[unsplash.DemoPhoto]) -> DemoImages:
    if not photos:
        return DemoImages()
    _, _, options = unsplash.choose_images(photos, sample.template)
    hero = options[sample.hero_index % len(options)] if options else None
    return DemoImages(hero=hero, mood=unsplash.mood_for(hero, options, sample.template), options=options)


def render(sample: Sample, images: DemoImages) -> str:
    # Hinnat näytteissä = hinnat "yrityksen omalta sivulta" (yksi näyte per pohja)
    has_prices = any(s.get("price") for s in sample.content["services"])
    stored = DemoStoredContent(
        **sample.content, price_note=price_note_for(sample.template, has_prices),
        opening_periods=sample.periods, images=images, timma=sample.timma,
    )
    return render_demo_html(
        template=sample.template, color_scheme=sample.palette, content=stored,
        business=DemoBusiness(
            name=sample.name, city=sample.city, address=sample.address, phone=sample.phone,
            maps_url="https://maps.google.com/?cid=1",
        ),
        sender=DemoSender(name="Carolus Palin", company_name="Palin Web", phone="040 111 2222", website="https://palinweb.fi"),
    )


def serve(out: Path) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (perityn metodin nimi)
            pass

        def do_GET(self) -> None:
            url = urlparse(self.path)
            parts = url.path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "a":
                asset = demo_asset(parts[1], parts[2])
                version = parse_qs(url.query).get("v", [""])[0]
                # Kuten Worker: väärä tai puuttuva ?v= -> 404 (testaa, että HTML ja CSS viittaavat oikeaan versioon)
                if asset is None or asset.digest != version:
                    self.send_error(404)
                    return
                self._send(asset.body, asset.content_type, {"Access-Control-Allow-Origin": "*"})
                return
            page = out / f"{parts[0]}.html"
            if len(parts) == 1 and page.is_file():
                self._send(page.read_bytes(), "text/html; charset=utf-8", {"Content-Security-Policy": CSP_V2})
                return
            self.send_error(404)

        def _send(self, body: bytes, content_type: str, headers: dict[str, str]) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# Sana on katkennut, jos sen merkit jakautuvat usealle riville
_BROKEN_WORDS_JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('h1, h2, h3, .logo, .nappi')) {
    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') continue;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      // Väliviivan jälkeen saa vaihtaa riviä ("Parturi-|kampaamo"), joten osat tarkistetaan erikseen
      const re = /[^\\s-]+-?/g; let m;
      while ((m = re.exec(node.textContent))) {
        const r = document.createRange(); r.setStart(node, m.index); r.setEnd(node, m.index + m[0].length);
        const tops = new Set([...r.getClientRects()].filter(x => x.width > 0).map(x => Math.round(x.top)));
        if (tops.size > 1) out.push(`${el.tagName.toLowerCase()}: ${m[0]}`);
      }
    }
  }
  return out;
}"""

_OVERFLOW_JS = """() => {
  const de = document.documentElement;
  const off = [...document.querySelectorAll('body *')]
    .filter(e => e.getBoundingClientRect().right > de.clientWidth + 0.5 && e.getBoundingClientRect().width > 0
                 && getComputedStyle(e.parentElement).overflow === 'visible' && !e.closest('.hero, .allas'))
    .slice(0, 3).map(e => `${e.tagName.toLowerCase()}.${e.className}`);
  return { sw: de.scrollWidth, cw: de.clientWidth, off };
}"""


def settle(page: Any) -> None:
    """Unsplashin CDN voi joskus pitää yhteyttä auki: networkidle ei saa kaataa ajoa."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeout:
        pass


def open_page(page: Any, url: str) -> None:
    page.goto(url, wait_until="load", timeout=60000)
    settle(page)


def browser_checks(base: str, samples: list[Sample], out: Path) -> int:
    from playwright.sync_api import sync_playwright

    shots = out / "kuvat"
    shots.mkdir(exist_ok=True)
    failures = 0
    with sync_playwright() as pw:
        for engine in (pw.chromium, pw.webkit):
            browser = engine.launch()
            for sample in samples:
                url = f"{base}/{sample.slug}?aika={TEST_TIME}"
                row: list[str] = []
                for width in WIDTHS:
                    context = browser.new_context(viewport={"width": width, "height": 844 if width < 768 else 900},
                                                  reduced_motion="reduce")
                    page = context.new_page()
                    errors: list[str] = []
                    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                    page.on("pageerror", lambda exc: errors.append(str(exc)))
                    open_page(page, url)
                    page.evaluate("document.fonts.ready")
                    if width in (390, 1440):
                        # Lazy-kuvat latautuvat vasta näkyviin vieritettäessä
                        page.evaluate("""async () => {
                          for (let y = 0; y < document.body.scrollHeight; y += innerHeight / 2) {
                            scrollTo(0, y); await new Promise(r => setTimeout(r, 60));
                          }
                          scrollTo(0, 0);
                          // Vieritystapahtuma ehtii perille ennen kuvakaappausta (premiumin heron ruutu)
                          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
                        }""")
                        settle(page)
                    overflow = page.evaluate(_OVERFLOW_JS)
                    broken = page.evaluate(_BROKEN_WORDS_JS)
                    problems = []
                    if overflow["sw"] > overflow["cw"]:
                        problems.append(f"ylivuoto {overflow['sw']}>{overflow['cw']} {overflow['off']}")
                    if broken:
                        problems.append(f"katkenneet sanat {broken[:3]}")
                    if errors:
                        problems.append(f"konsoli {errors[:2]}")
                    if width in (390, 1440):
                        page.screenshot(path=str(shots / f"{sample.slug}-{engine.name}-{width}.png"),
                                        full_page=engine.name == "chromium")
                        page.screenshot(path=str(shots / f"{sample.slug}-{engine.name}-{width}-ruutu.png"))
                    failures += bool(problems)
                    row.append(f"{width} ok" if not problems else f"{width}: {'; '.join(problems)}")
                    context.close()
                print(f"  {engine.name:8} {sample.slug:24} " + " · ".join(row))

            # Ilman JavaScriptiä: viikkoaikataulu ja Tänään-rivi näkyvät HTML:stä
            for sample in samples:
                context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
                page = context.new_page()
                open_page(page, f"{base}/{sample.slug}")
                text = page.inner_text("body")
                ok = (not sample.periods) or ("Maanantai" in text and "Tänään" in text)
                failures += not ok
                print(f"  {engine.name:8} {sample.slug:24} ilman JS: {'ok' if ok else 'AIKATAULU PUUTTUU'}")
                context.close()
            browser.close()
    return failures


# --- Premium-hero liike päällä ---

_HERO_STATE_JS = """() => {
  const napit = [...document.querySelectorAll('.hero .napit .nappi')].map(a => a.getBoundingClientRect().bottom);
  const n = document.querySelector('.hero .napit'), t = document.querySelector('.hero .tiedot');
  const logo = document.querySelector('.logo'), tyyli = getComputedStyle(logo);
  return {
    canvas: !!document.querySelector('.tausta.on-elokuva .elokuva'),
    cta: Math.max(...napit), ensimmainen: napit[0], korkeus: innerHeight,
    vali: t ? t.getBoundingClientRect().top - n.getBoundingClientRect().bottom : 0,
    katkeaa: tyyli.textOverflow === 'ellipsis' || tyyli.whiteSpace === 'nowrap'
      || logo.scrollWidth > logo.clientWidth + 1 || logo.scrollHeight > logo.clientHeight + 1,
    himmea: getComputedStyle(document.documentElement).getPropertyValue('--himmea').trim(),
  };
}"""

# Canvasin sisällön tunniste yhdeltä vaakakaistalta: muuttuu, kun piirretty ruutu vaihtuu
_FRAME_SIG_JS = """() => {
  const c = document.querySelector('.elokuva');
  if (!c) return null;
  const d = c.getContext('2d').getImageData(0, Math.floor(c.height * 0.3), c.width, 4).data;
  let s = 0;
  for (let i = 0; i < d.length; i += 4) s = (s * 31 + d[i]) % 1000000007;
  return s;
}"""

_SCROLL_HERO_JS = """f => {
  const h = document.querySelector('.hero');
  scrollTo({ top: f * (h.getBoundingClientRect().bottom + scrollY), behavior: 'instant' });
}"""

# Heron ja yläpalkin tekstit, jotka ovat nyt ruudulla heron kohdalla (napeilla on oma taustansa)
_TEXT_RECTS_JS = """() => {
  const hero = document.querySelector('.hero').getBoundingClientRect();
  const out = [];
  const valitsin = '.yla .logo, .yla-linkit a, .hero .tila, .hero h1, .hero-lause, .hero .tiedot dt, .hero .tiedot dd';
  for (const el of document.querySelectorAll(valitsin)) {
    const r = el.getBoundingClientRect();
    const yla = Math.max(0, r.top, hero.top), ala = Math.min(innerHeight, r.bottom, hero.bottom);
    if (r.width < 4 || ala - yla < 4) continue;
    out.push({ x: Math.max(0, r.left), y: yla, w: Math.min(innerWidth, r.right) - Math.max(0, r.left), h: ala - yla,
               nimi: el.className || el.tagName.toLowerCase() });
  }
  return out;
}"""

_SHOW_TEXT_JS = """nakyy => document.querySelectorAll('.yla-sisa, .hero-sisa')
  .forEach(e => { e.style.visibility = nakyy ? '' : 'hidden'; })"""

# Kirkkain 4 × 4 px keskiarvo tekstialueiden alla (yksittäinen rakeen pikseli ei ratkaise luettavuutta)
_BRIGHTEST_JS = """async ({ png, rects }) => {
  const img = new Image();
  img.src = 'data:image/png;base64,' + png;
  await img.decode();
  const c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0);
  const lin = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  let pahin = { l: -1, rgb: [0, 0, 0], nimi: '' };
  for (const r of rects) {
    const x0 = Math.floor(r.x), y0 = Math.floor(r.y), w = Math.floor(r.w), h = Math.floor(r.h);
    if (w < 4 || h < 4) continue;
    const d = g.getImageData(x0, y0, w, h).data;
    for (let by = 0; by + 4 <= h; by += 4) for (let bx = 0; bx + 4 <= w; bx += 4) {
      let R = 0, G = 0, B = 0;
      for (let y = by; y < by + 4; y++) for (let x = bx; x < bx + 4; x++) {
        const i = (y * w + x) * 4; R += d[i]; G += d[i + 1]; B += d[i + 2];
      }
      R /= 16; G /= 16; B /= 16;
      const l = 0.2126 * lin(R) + 0.7152 * lin(G) + 0.0722 * lin(B);
      if (l > pahin.l) pahin = { l, rgb: [Math.round(R), Math.round(G), Math.round(B)], nimi: r.nimi };
    }
  }
  return pahin;
}"""


def _luminance(hex_color: str) -> float:
    def lin(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _brightest_under_text(page: Any) -> dict[str, Any]:
    rects = page.evaluate(_TEXT_RECTS_JS)
    page.evaluate(_SHOW_TEXT_JS, False)
    png = base64.b64encode(page.screenshot()).decode()
    page.evaluate(_SHOW_TEXT_JS, True)
    return page.evaluate(_BRIGHTEST_JS, {"png": png, "rects": rects})


def premium_hero_checks(base: str, samples: list[Sample]) -> int:
    """Hero liike päällä: ruutusarja, nappi ilman vieritystä, nimi, väli ja tekstin kontrasti kuvan päällä."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    failures = 0
    brightest: dict[str, dict[str, Any]] = {}
    with sync_playwright() as pw:
        for engine in (pw.chromium, pw.webkit):
            browser = engine.launch()
            for sample in samples:
                row: list[str] = []
                for width, height in ((390, 844), (1440, 900)):
                    context = browser.new_context(viewport={"width": width, "height": height})
                    page = context.new_page()
                    errors: list[str] = []
                    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                    page.on("pageerror", lambda exc: errors.append(str(exc)))
                    open_page(page, f"{base}/{sample.slug}?aika={TEST_TIME}")
                    problems = []
                    try:
                        page.wait_for_selector(".tausta.on-elokuva .elokuva", timeout=8000)
                    except PlaywrightTimeout:
                        problems.append("ruutusarja ei käynnistynyt")
                    # Alkuliike (1,6 s) ja tekstien nousu loppuun, loput ruudut ladattu
                    page.wait_for_timeout(2600)
                    settle(page)
                    state = page.evaluate(_HERO_STATE_JS)
                    if state["cta"] > state["korkeus"]:
                        problems.append(f"nappi vaatii vierityksen ({state['cta']:.0f} > {state['korkeus']})")
                    if state["katkeaa"]:
                        problems.append("yläpalkin nimi katkeaa")
                    if width < 768 and state["ensimmainen"] > PHONE_CTA_MAX:
                        problems.append(f"ensimmäinen nappi liian alhaalla ({state['ensimmainen']:.0f} > {PHONE_CTA_MAX})")
                    if width < 768 and state["vali"] > 40:
                        problems.append(f"tyhjä väli nappien ja tietojen välissä {state['vali']:.0f} px")
                    if width < 768:
                        # Yläpalkin nappi piilossa niin kauan kuin heron nappi näkyy
                        shown = page.evaluate("() => getComputedStyle(document.querySelector('.yla .nappi-pieni')).visibility")
                        if shown != "hidden":
                            problems.append("yläpalkin nappi näkyy heron napin kanssa")
                    ratios: list[float] = []
                    before = page.evaluate(_FRAME_SIG_JS)
                    for fraction in (0, 0.2, 0.4, 0.6):
                        page.evaluate(_SCROLL_HERO_JS, fraction)
                        page.wait_for_timeout(700)
                        if engine.name != "chromium":
                            continue
                        worst = _brightest_under_text(page)
                        if worst["l"] < 0:
                            continue
                        ratio = (_luminance(state["himmea"]) + 0.05) / (worst["l"] + 0.05)
                        ratios.append(ratio)
                        if ratio < 4.5:
                            problems.append(f"kontrasti {ratio:.2f} ({worst['nimi']}, vieritys {fraction})")
                        key = sample.palette
                        if key not in brightest or worst["l"] > brightest[key]["l"]:
                            brightest[key] = worst
                    if before is not None and page.evaluate(_FRAME_SIG_JS) == before:
                        problems.append("ruutu ei vaihdu vierittäessä")
                    if errors:
                        problems.append(f"konsoli {errors[:2]}")
                    failures += bool(problems)
                    note = f", kontrasti min {min(ratios):.2f}" if ratios else ""
                    row.append(f"{width} ok{note}" if not problems else f"{width}: {'; '.join(problems)}")
                    context.close()
                print(f"  {engine.name:8} {sample.slug:24} " + " · ".join(row))

            # Ilman JavaScriptiä: still näkyy, canvasia ei ole
            for sample in samples:
                context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
                page = context.new_page()
                open_page(page, f"{base}/{sample.slug}")
                box = page.locator(".tausta .still").bounding_box()
                ok = bool(box and box["width"] > 300 and box["height"] > 200) and page.locator(".elokuva").count() == 0
                failures += not ok
                print(f"  {engine.name:8} {sample.slug:24} ilman JS: {'still ok' if ok else 'STILL PUUTTUU'}")
                context.close()
            browser.close()
    for palette, worst in brightest.items():
        print(f"  {palette}: kirkkain tausta tekstin alla #{''.join(f'{v:02X}' for v in worst['rgb'])} ({worst['nimi']})")
    return failures


def contact_sheet(samples: list[Sample], out: Path) -> Path:
    """390 px ensimmäinen ruutu ja 1440 px ensimmäinen ruutu rinnakkain, pohjittain."""
    from playwright.sync_api import sync_playwright

    cells = "".join(
        f"<figure><figcaption>{s.name} · {s.palette}{'' if s.periods else ' · ei aukioloja'}</figcaption>"
        f"<div class=r><img class=m src='kuvat/{s.slug}-chromium-390-ruutu.png'>"
        f"<img class=m src='kuvat/{s.slug}-webkit-390-ruutu.png'>"
        f"<img class=d src='kuvat/{s.slug}-chromium-1440-ruutu.png'></div></figure>"
        for s in samples
    )
    sheet = out / "arkki.html"
    sheet.write_text(
        "<!doctype html><meta charset=utf-8><style>body{margin:0;padding:24px;background:#ddd;font:14px system-ui}"
        "figure{margin:0 0 24px}figcaption{margin-bottom:8px;font-weight:600}.r{display:flex;gap:12px;align-items:flex-start}"
        ".m{width:300px}.d{width:820px}img{border:1px solid #999;background:#fff}</style>"
        "<p>Vasemmalla Chromium 390 px, keskellä WebKit 390 px, oikealla Chromium 1440 px (ensimmäinen ruutu)</p>"
        + cells
    )
    png = out / "arkki.png"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.goto(sheet.as_uri())
        page.screenshot(path=str(png), full_page=True)
        browser.close()
    return png


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--template", choices=[t for t, v in TEMPLATES.items() if v.version >= 2])
    parser.add_argument("--serve", action="store_true", help="jätä palvelin käyntiin selaintestien jälkeen")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    samples = [s for s in SAMPLES if not args.template or s.template == args.template]
    failures = 0
    print("Tekstit:")
    for sample in samples:
        problems = check_texts(sample)
        failures += bool(problems)
        print(f"  {sample.slug:24} {'ok' if not problems else problems}")

    print("Renderöinti:")
    for sample in samples:
        photos = load_photos(sample.template, sample.primary_type, out)
        html = render(sample, images_for(sample, photos))
        (out / f"{sample.slug}.html").write_text(html)
        print(f"  {sample.slug:24} {len(html.encode()) // 1024} kt, kuvia {len(photos)}")

    server = serve(out)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Selaintestit ({base}):")
    failures += browser_checks(base, samples, out)
    premium = [s for s in samples if s.template == "premium"]
    if premium:
        print("Premium-hero liike päällä:")
        failures += premium_hero_checks(base, premium)
    print(f"Arkki: {contact_sheet(samples, out)}")
    if args.serve:
        print(f"Palvelin käynnissä: {base}/<slug>  (Ctrl+C lopettaa)")
        threading.Event().wait()
    print("OK" if not failures else f"{failures} ongelmaa")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
