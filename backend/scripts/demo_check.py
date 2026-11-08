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
"""
import argparse
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
    OpeningPeriod,
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
    "img-src data: https://images.unsplash.com; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
WIDTHS = [320, 360, 375, 390, 414, 768, 1024, 1280, 1440]
# Kiinteä testihetki: tiistai klo 12 (aukiolo.js lukee ?aika=)
TEST_TIME = "2026-11-10T12:00"


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
                {"name": "Pullat ja piirakat", "description": "Voisilmäpullat, korvapuustit ja marjapiirakat."},
                {"name": "Täytekakut", "description": "Kakut juhliin tilauksesta, kysykää vaihtoehtoja."},
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
                {"name": "Leikkaus", "description": "Leikkaus ja föönaus toiveidenne mukaan."},
                {"name": "Värjäys", "description": "Kestovärit, raidat ja sävytykset."},
                {"name": "Kampaukset", "description": "Juhla- ja hääkampaukset tilaisuuksiin."},
                {"name": "Kulmien muotoilu", "description": "Muotoilu ja värjäys kulmille sekä ripsille."},
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
                {"name": "Hiustenleikkaus", "description": "Saksi- ja koneleikkaukset."},
                {"name": "Parranajo", "description": "Parranajo kuumapyyhkeellä."},
                {"name": "Parran muotoilu", "description": "Ääriviivat ja tasaus koneella."},
                {"name": "Kulmat ja korvat", "description": "Siistiminen leikkauksen yhteydessä."},
            ],
        },
        periods=[],
        hero_index=1,
    ),
]


def check_texts(sample: Sample) -> list[str]:
    content = DemoContent(**sample.content, price_note=price_note_for(sample.template))
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
    stored = DemoStoredContent(
        **sample.content, price_note=price_note_for(sample.template),
        opening_periods=sample.periods, images=images,
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
    print(f"Arkki: {contact_sheet(samples, out)}")
    if args.serve:
        print(f"Palvelin käynnissä: {base}/<slug>  (Ctrl+C lopettaa)")
        threading.Event().wait()
    print("OK" if not failures else f"{failures} ongelmaa")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
