"""Demonettisivun generointi liidille.

AI ei kirjoita HTML:ää: se tuottaa vain sisällön JSON-muodossa (DemoAIContent), joka validoidaan
tiukasti. HTML renderöidään valmiista Jinja2-pohjasta (autoescape), joten jokainen demo on
teknisesti toimiva, nopea, mobiiliystävällinen ja turvallinen.

Pohjia on kahta muotoa:
- versio 1 (beauty, restaurant, services): yksi HTML-tiedosto, inline-CSS, fontit base64:nä, ei JS:ää
- versio 2 (cafe, ...): HTML + erilliset CSS-, JS- ja fonttitiedostot (`assets/`), joihin viitataan
  suhteellisella polulla `a/{ryhmä}/{tiedosto}?v={tiiviste}`. Sama HTML toimii backendin esikatselussa
  (/demo/{polku} -> /demo/a/...) ja Workerissa (/{polku} -> /a/...). Ei inline-tyylejä eikä -skriptejä,
  joten CSP voi olla `style-src 'self'; script-src 'self'`.
"""
import base64
import hashlib
import json
import logging
import re
import secrets
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .demo_icons import icon_svg, service_icon_names
from .text_quality import find_forbidden_words, repeated_phrases
from .utils.unsplash import DemoPhoto, photo_url, unsplash_home_url, with_utm

logger = logging.getLogger(__name__)

PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
# Vain aukioloajat (Place Details Enterprise -SKU, ~$0.02 / kutsu). Ei muita kenttiä: field mask määrää hinnan.
PLACE_DETAILS_FIELD_MASK = "regularOpeningHours"

DEFAULT_PRICE_NOTE = "Hinnat ja ajanvaraus puhelimitse."
TOKEN_BYTES = 32  # secrets.token_urlsafe(32) -> 43 merkkiä, 256 bittiä satunnaisuutta


# --- Pohjat ja värit ---

@dataclass(frozen=True)
class ColorScheme:
    label: str
    bg: str
    surface: str
    text: str
    muted: str
    primary: str
    on_primary: str
    hero_from: str
    hero_to: str
    on_hero: str


@dataclass(frozen=True)
class Palette:
    """Versio 2: värit ovat pohjan CSS:ssä (`[data-paletti="..."]`), tässä vain nimi ja selaimen teemaväri."""
    label: str
    theme: str


@dataclass(frozen=True)
class DemoTemplate:
    label: str
    services_title: str
    services_lead: str  # kiinteä teksti; mukana toistotarkistuksessa
    schemes: dict[str, ColorScheme | Palette]
    version: int = 1
    price_note: str = DEFAULT_PRICE_NOTE
    about_title: str = "Tietoa meistä"  # jos AI ei anna about_titlea


# Värit valittu niin, että tekstin kontrasti taustaa vasten on vähintään WCAG AA (4.5:1)
TEMPLATES: dict[str, DemoTemplate] = {
    "cafe": DemoTemplate(
        label="Café",
        services_title="Valikoima",
        services_lead="Päivän valikoiman näette tiskiltä.",
        price_note="Hinnat tiskillä ja puhelimitse.",
        about_title="Meistä",
        version=2,
        # Kontrastit: tests/test_demo_v2.py laskee jokaisen paletin teksti/pinta-parit tyylit.css:stä
        schemes={
            "paahto": Palette("Roast", "#E3E4CF"),
            "kaura": Palette("Oat", "#E4E4DE"),
            "ruis": Palette("Rye", "#E7E1DB"),
        },
    ),
    "beauty": DemoTemplate(
        label="Classic hair & beauty",
        services_title="Palvelut",
        services_lead="Varatkaa aika puhelimitse.",
        schemes={
            "rose": ColorScheme("Rose", "#fdf7f7", "#ffffff", "#2b1d21", "#5f4b52", "#9d2f55", "#ffffff", "#5b1a33", "#9d2f55", "#ffffff"),
            "sage": ColorScheme("Sage", "#f6f8f5", "#ffffff", "#1f2a22", "#4d5a50", "#3f6b4f", "#ffffff", "#24412f", "#4f7d60", "#ffffff"),
            "noir": ColorScheme("Noir", "#f7f6f4", "#ffffff", "#1c1b1a", "#55524e", "#1c1b1a", "#ffffff", "#111111", "#3a3632", "#ffffff"),
        },
    ),
    "restaurant": DemoTemplate(
        label="Classic restaurant & café",
        services_title="Mitä tarjoamme",
        services_lead="Tutustukaa valikoimaamme.",
        schemes={
            "terracotta": ColorScheme("Terracotta", "#fbf6f1", "#ffffff", "#2a1f18", "#5e5048", "#a2452a", "#ffffff", "#6b2a17", "#a2452a", "#ffffff"),
            "olive": ColorScheme("Olive", "#f8f8f2", "#ffffff", "#24261b", "#55584a", "#5b6327", "#ffffff", "#353a15", "#5b6327", "#ffffff"),
            "night": ColorScheme("Night", "#f4f5f8", "#ffffff", "#161a24", "#4b5262", "#2e3a70", "#ffffff", "#121831", "#2e3a70", "#ffffff"),
        },
    ),
    "services": DemoTemplate(
        label="Classic services",
        services_title="Palvelut",
        services_lead="Kysykää lisää puhelimitse.",
        schemes={
            "ocean": ColorScheme("Ocean", "#f4f8fb", "#ffffff", "#132230", "#4a5a68", "#1d5d8c", "#ffffff", "#0f3554", "#1d5d8c", "#ffffff"),
            "slate": ColorScheme("Slate", "#f5f6f7", "#ffffff", "#1b1f24", "#50575f", "#36414d", "#ffffff", "#1f262e", "#46525f", "#ffffff"),
            "forest": ColorScheme("Forest", "#f4f7f4", "#ffffff", "#17241a", "#4a584d", "#2f6a3f", "#ffffff", "#173b22", "#2f6a3f", "#ffffff"),
        },
    ),
}
DEFAULT_TEMPLATE = "services"

_BEAUTY_TYPES = ("hair", "barber", "beauty", "nail", "spa", "salon", "makeup", "massage", "tanning", "lash", "brow")
# Kokonaiset sanat ("tea" osuisi muuten steak_houseen): coffee_shop, tea_house, cake_shop, bakery, cafe
_CAFE_WORDS = {"cafe", "cafeteria", "coffee", "bakery", "tea", "cake", "pastry"}
_RESTAURANT_TYPES = ("restaurant", "cafe", "coffee", "bakery", "bar", "pub", "pizza", "food", "meal", "diner", "bistro", "deli", "ice_cream", "tea")


def template_for_primary_type(primary_type: Optional[str]) -> str:
    t = (primary_type or "").lower()
    if any(k in t for k in _BEAUTY_TYPES):
        return "beauty"
    # Kahvila ennen ravintoloita: "cafe" osuu myös _RESTAURANT_TYPES-listaan
    if _CAFE_WORDS & set(re.split(r"[^a-z]+", t)):
        return "cafe"
    if any(k in t for k in _RESTAURANT_TYPES):
        return "restaurant"
    return DEFAULT_TEMPLATE


def default_scheme(template: str) -> str:
    return next(iter(TEMPLATES[template].schemes))


def validate_template_choice(template: str, color_scheme: Optional[str]) -> tuple[str, str]:
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template '{template}'")
    scheme = color_scheme or default_scheme(template)
    if scheme not in TEMPLATES[template].schemes:
        # Pohjaa vaihdettaessa vanha väri ei välttämättä kuulu uuteen pohjaan
        scheme = default_scheme(template)
    return template, scheme


def templates_catalog() -> list[dict[str, object]]:
    # Uudet (versio 2) ensin valikossa
    ordered = sorted(TEMPLATES.items(), key=lambda item: -item[1].version)
    return [
        {
            "id": tid,
            "label": t.label,
            "version": t.version,
            "color_schemes": [{"id": sid, "label": s.label} for sid, s in t.schemes.items()],
        }
        for tid, t in ordered
    ]


def price_note_for(template: str) -> str:
    return TEMPLATES.get(template, TEMPLATES[DEFAULT_TEMPLATE]).price_note


# --- Sisältöskeema ---

class DemoService(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=60)
    description: str = Field(min_length=10, max_length=140)  # yksi lyhyt lause


class DemoAIContent(BaseModel):
    """Mallin palauttama sisältö. Ei hintoja, aukioloaikoja eikä yhteystietoja: ne tulevat koodista."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    hero_title: str = Field(min_length=5, max_length=80)
    hero_subtitle: str = Field(min_length=10, max_length=180)
    # Esittelyosion otsikko (versio 2 -pohjat). Valinnainen: vanhoissa demoissa ei ole
    about_title: Optional[str] = Field(default=None, min_length=2, max_length=50)
    about: str = Field(min_length=40, max_length=700)
    services: list[DemoService] = Field(min_length=3, max_length=6)


class DemoContent(DemoAIContent):
    """Tallennettu ja käyttäjän muokattavissa oleva sisältö."""
    price_note: str = Field(default=DEFAULT_PRICE_NOTE, min_length=5, max_length=120)


class DemoImages(BaseModel):
    """Unsplash-kuvat (hotlinkattavat URLit + attribuutiotiedot). hero None -> gradientti."""
    hero: Optional[DemoPhoto] = None
    mood: list[DemoPhoto] = Field(default_factory=list, max_length=3)
    options: list[DemoPhoto] = Field(default_factory=list, max_length=8)


class OpeningPeriod(BaseModel):
    """Yksi aukiolojakso yhdelle päivälle. Keskiyön yli jatkuva jakso on jaettu kahdelle päivälle."""
    day: int = Field(ge=0, le=6)  # Googlen numerointi: 0 = sunnuntai
    open: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    close: str = Field(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")  # 24:00 = keskiyö


class DemoStoredContent(DemoContent):
    # Haettu Place Detailsista generoinnin hetkellä; osa demoa, ei erillistä Places-välimuistia
    opening_hours: list[str] = Field(default_factory=list, max_length=7)
    # Samasta vastauksesta (sama field mask): koneluettavat ajat aukiolo.js:lle. Tyhjä vanhoissa demoissa
    opening_periods: list[OpeningPeriod] = Field(default_factory=list, max_length=28)
    images: DemoImages = Field(default_factory=DemoImages)


# Keksityt faktat: arvostelut, palkinnot, historia, sitaatit (label, regex)
_INVENTED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in [
        ("arvostelut", r"\barvostel\w*|\btähde\w*|\btähti\w*|\b\w*arvosan\w*"),
        ("palkinnot", r"\bpalki\w*|\bpalkinto\w*|\bvoittaja\w*|\bvoitti\b"),
        ("historia", r"\bperustet\w*|\bvuodesta\b|\bvuosikymmen\w*|\bvuosien\s+kokemu\w*|\bsukupolv\w*"),
        ("asiakaskehut", r"\basiakkaa(mme|t)\s+(sanovat|kertovat|kehuvat|suosittelevat|rakastavat)\b|\btyytyväi\w*\s+asiak\w*"),
        ("hinnat", r"€|\beuro\w*|\bhinta(an|aan)?\s+alk\w*|\balkaen\b"),
    ]
]
_QUOTE_CHARS = "\"“”„«»"
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?:])\s+")
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s+[A-ZÅÄÖ])")
_WORD_RE = re.compile(r"[A-Za-zÅÄÖåäöÉéÜü][\wÅÄÖåäöÉéÜü'-]*")


# Yleiset erisnimet, joita saa mainita ilman lähdettä
_ALWAYS_ALLOWED = {"google", "suomi", "suomen", "suomessa"}
# Suomen taivutus: "Kauniaisissa" ~ "Kauniainen", "Tainan" ~ "Taina" -> verrataan sanan alkua
_STEM_LEN = 5


def _allowed_vocabulary(*sources: Optional[str]) -> set[str]:
    words: set[str] = set(_ALWAYS_ALLOWED)
    for source in sources:
        for w in _WORD_RE.findall(source or ""):
            words.add(w.lower())
    return words


def _is_allowed_word(word: str, allowed: set[str]) -> bool:
    w = word.lower()
    if w in allowed:
        return True
    stem = w[:_STEM_LEN]
    return len(stem) >= 4 and any(a.startswith(stem) for a in allowed if len(a) >= 4)


def content_violations(content: DemoAIContent, *, allowed_text: str) -> list[str]:
    """Sisältösäännöt, joita Pydantic-skeema ei kata. Tyhjä lista = hyväksytty.

    allowed_text = yrityksen nimi, kaupunki ja Deep Scan -teksti: niissä esiintyvät
    erisnimet (esim. tuotemerkit sivuilta) ovat sallittuja, muut isolla alkavat sanat
    lauseen keskellä tulkitaan keksityiksi nimiksi.
    """
    fields: list[tuple[str, str]] = [
        ("hero_title", content.hero_title),
        ("hero_subtitle", content.hero_subtitle),
        ("about", content.about),
    ]
    if content.about_title:
        fields.append(("about_title", content.about_title))
    for i, s in enumerate(content.services):
        fields.append((f"services[{i}].name", s.name))
        fields.append((f"services[{i}].description", s.description))

    allowed = _allowed_vocabulary(allowed_text)
    problems: list[str] = []
    for field, text in fields:
        for word in find_forbidden_words(text):
            problems.append(f"{field}: kielletty sana '{word}'")
        if re.search(r"\d", text):
            problems.append(f"{field}: sisältää numeroita (ei hintoja, vuosilukuja tai määriä)")
        if any(ch in text for ch in _QUOTE_CHARS):
            problems.append(f"{field}: sisältää lainausmerkkejä (ei sitaatteja)")
        for label, pattern in _INVENTED_PATTERNS:
            if pattern.search(text):
                problems.append(f"{field}: keksittyä sisältöä ({label})")
        if field.endswith(".description") and len(_SENTENCE_END_RE.findall(text.rstrip(".!? "))) > 0:
            problems.append(f"{field}: palvelukuvaus saa olla vain yksi lause")
        if not field.endswith(".name") and field not in ("hero_title", "about_title"):
            for sentence in _SENTENCE_SPLIT_RE.split(text):
                for word in _WORD_RE.findall(sentence)[1:]:
                    if word[0].isupper() and not _is_allowed_word(word, allowed):
                        problems.append(f"{field}: mahdollinen keksitty nimi '{word}'")
    return problems


class DemoGenerationError(Exception):
    pass


def extract_json_object(text: str) -> dict[str, object]:
    """Malli voi kääriä JSONin ```-lohkoon tai lisätä tekstiä: otetaan ensimmäinen {...}."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Vastauksessa ei ole JSON-objektia")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON ei ole objekti")
    return data


def page_texts(content: DemoAIContent, *, business_name: str, template: str, price_note: str = DEFAULT_PRICE_NOTE) -> list[str]:
    """Kaikki sivulla näkyvät tekstikappaleet toistotarkistusta varten (AI + pohjan kiinteät)."""
    tpl = TEMPLATES.get(template, TEMPLATES[DEFAULT_TEMPLATE])
    texts = [business_name, content.hero_title, content.hero_subtitle, content.about, tpl.services_lead, price_note]
    if content.about_title:
        texts.append(content.about_title)
    for s in content.services:
        texts.extend([s.name, s.description])
    return texts


def find_repeated_phrases(content: DemoAIContent, *, business_name: str, template: str) -> list[str]:
    return repeated_phrases(
        page_texts(content, business_name=business_name, template=template, price_note=price_note_for(template))
    )


def parse_ai_content(text: str, *, allowed_text: str) -> tuple[Optional[DemoAIContent], list[str]]:
    try:
        content = DemoAIContent.model_validate(extract_json_object(text))
    except (ValueError, ValidationError) as e:
        return None, [f"skeemavirhe: {e}"[:1500]]
    problems = content_violations(content, allowed_text=allowed_text)
    return (content if not problems else None), problems


DEMO_SYSTEM_PROMPT = """Kirjoitat suomenkielisen sisällön paikallisen yrityksen nettisivun LUONNOKSEEN.

Palauta VAIN yksi JSON-objekti täsmälleen tällä rakenteella (ei muuta tekstiä, ei markdownia):
{
  "hero_title": "sivun pääotsikko: lyhyt, luonteva lause, 5-60 merkkiä, EI saa toistaa yrityksen nimen sanoja, esim. Hiukset kuntoon Kauniaisissa",
  "hero_subtitle": "yksi lyhyt, luonteva lause siitä mitä yritys tarjoaa, 10-120 merkkiä",
  "about_title": "esittelyosion otsikko, 2-6 sanaa, ei yrityksen nimeä, esim. Rauhallinen paikka keskustassa",
  "about": "2-4 lyhyttä lausetta yrityksestä, 40-700 merkkiä",
  "services": [{"name": "palvelun nimi, 2-60 merkkiä", "description": "yksi lause, 10-220 merkkiä"}]
}
services: 3-6 kappaletta, mieluiten 4 tai 6. Palvelun nimi lyhyt (1-3 sanaa).

KIRJOITUSTYYLI — kuin oikea alan yrittäjä puhuisi asiakkaalle, ei mainostoimisto:
- Lyhyttä, konkreettista arkikieltä. Kerro mitä tehdään, ei adjektiiveja.
- Palvelun kuvaus: TÄSMÄLLEEN YKSI lyhyt lause (max ~12 sanaa).
  Hyvä: "Leikkaus, pesu ja föönaus samalla käynnillä." / "Kestovärit, raidat ja sävytykset."
  Huono: "Leikkaamme hiukset ja autamme teitä ylläpitämään toivomaanne mallia."
- about: 2-3 lyhyttä lausetta, max ~300 merkkiä. Älä toista yrityksen nimeä (se on jo sivun otsikkona).
- MIKÄÄN fraasi ei saa toistua sivulla: älä aloita lauseita samalla tavalla, älä toista samoja sanapareja
  eri kohdissa (esim. "autamme teitä", "hiusten leikkaus" kahteen kertaan).
- Sivulla on jo valmiina tekstit "Varatkaa aika puhelimitse." / "Hinnat ja ajanvaraus puhelimitse." — älä toista niitä.

SÄÄNNÖT:
- Yritys puhuu me-muodossa, asiakasta puhutellaan te-muodossa.
- Palvelut: alan tyypilliset palvelut. Jos VERKKOSIVUN SISÄLTÖ on annettu, käytä ensisijaisesti sieltä löytyviä palveluita.
- ÄLÄ keksi faktoja. Ehdottomasti kielletty: hinnat, numerot, vuosiluvut, kokemusvuodet, arvostelut, tähdet,
  asiakkaiden kehut, sitaatit tai lainausmerkit, palkinnot, sertifikaatit, henkilöiden nimet, yrityksen historia.
- Kirjoita yleisesti paikkansapitävää: mitä palvelu on ja miksi se on asiakkaalle hyödyllinen.
- Ei yhteystietoja, aukioloaikoja eikä hintoja (ne lisätään sivulle muualta).
- Kielletyt sanat: ihana, upea, mahtava, ainutlaatuinen, intohimo, ratkaisu, kokonaisvaltainen, digitaalinen läsnäolo,
  nostaa seuraavalle tasolle, innovatiivinen, räätälöity, huippu-, saumaton, synergia, autamme, tarjoamme laadukasta,
  tervetuloa huolehtimaan. Ei mainoskliseitä.
- Selkeä, rauhallinen ja asiallinen sävy. Lyhyet lauseet."""


def build_demo_prompt(*, name: str, city: str, primary_type: Optional[str], website_context: Optional[str]) -> str:
    parts = [
        f"Yritys: {name}",
        f"Kaupunki: {city}",
        f"Toimiala (Googlen luokka englanniksi): {primary_type or 'ei tiedossa'}",
    ]
    if website_context:
        parts.append(f"\nVERKKOSIVUN SISÄLTÖ (yrityksen nykyiseltä sivulta):\n{website_context}")
    parts.append("\nKirjoita sivun sisältö JSON-muodossa.")
    return "\n".join(parts)


def retry_prompt(original: str, problems: list[str]) -> str:
    issues = "\n".join(f"- {p}" for p in problems[:15])
    return f"{original}\n\nEDELLINEN VASTAUS HYLÄTTIIN näiden syiden vuoksi:\n{issues}\nKorjaa ja palauta koko JSON uudelleen."


# --- Place Details (New): aukioloajat ---

@dataclass(frozen=True)
class OpeningHours:
    descriptions: list[str]  # Googlen valmiit rivit, esim. "maanantai: 9.00–17.00"
    periods: list[OpeningPeriod]


def _hhmm(point: dict[str, object]) -> str:
    hour, minute = point.get("hour", 0), point.get("minute", 0)
    return f"{int(hour) if isinstance(hour, int) else 0:02d}:{int(minute) if isinstance(minute, int) else 0:02d}"


def periods_from_google(raw: object) -> list[OpeningPeriod]:
    """regularOpeningHours.periods -> päiväkohtaiset jaksot.

    Jakso ilman closea = auki ympäri vuorokauden. Keskiyön yli jatkuva jakso jaetaan:
    pe 18-02 -> pe 18:00-24:00 + la 00:00-02:00. Virheellinen rivi ohitetaan.
    """
    if not isinstance(raw, list):
        return []
    result: list[OpeningPeriod] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start, end = item.get("open"), item.get("close")
        if not isinstance(start, dict) or not isinstance(start.get("day"), int):
            continue
        if end is None:
            return [OpeningPeriod(day=d, open="00:00", close="24:00") for d in range(7)]
        if not isinstance(end, dict) or not isinstance(end.get("day"), int):
            continue
        day, open_at, close_day, close_at = int(start["day"]) % 7, _hhmm(start), int(end["day"]) % 7, _hhmm(end)
        span = (close_day - day) % 7
        try:
            if span == 0:
                result.append(OpeningPeriod(day=day, open=open_at, close=close_at))
                continue
            result.append(OpeningPeriod(day=day, open=open_at, close="24:00"))
            for offset in range(1, span):
                result.append(OpeningPeriod(day=(day + offset) % 7, open="00:00", close="24:00"))
            if close_at != "00:00":
                result.append(OpeningPeriod(day=close_day, open="00:00", close=close_at))
        except ValidationError:
            continue
    return sorted(result, key=lambda p: (p.day, p.open))[:28]


def fetch_opening_hours(place_id: str, api_key: str) -> Optional[OpeningHours]:
    """Yksi Place Details -kutsu, vain regularOpeningHours. None jos ei saatavilla tai virhe."""
    try:
        r = requests.get(
            PLACE_DETAILS_URL.format(place_id=place_id),
            params={"languageCode": "fi"},
            headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": PLACE_DETAILS_FIELD_MASK},
            timeout=10,
        )
        if r.status_code >= 400:
            logger.warning(f"Place Details {r.status_code}: {r.text[:300]}")
            return None
        regular = r.json().get("regularOpeningHours") or {}
        descriptions = [str(h)[:80] for h in regular.get("weekdayDescriptions") or []][:7]
        if not descriptions:
            return None
        return OpeningHours(descriptions=descriptions, periods=periods_from_google(regular.get("periods")))
    except Exception as e:
        logger.warning(f"Place Details epäonnistui ({place_id}): {e}")
        return None


# --- Renderöinti ---

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "demo"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"], default=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def new_public_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


# --- Luettava julkinen osoite: /{nimi}-{satunnainen}, esim. /taina-lantiainen-k7x2m ---
# Satunnaisosa ilman sekoittuvia merkkejä (0/o, 1/l/i): 31^5 ≈ 28,6 milj. vaihtoehtoa per nimi.
# Riittää, koska demot ovat noindex, vanhenevat 30 päivässä eikä osoitteita voi listata
# (R2-bucket ei ole julkinen, Worker palvelee vain tarkan avaimen, robots.txt Disallow).
SLUG_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
SLUG_SUFFIX_LEN = 5
SLUG_NAME_MAX = 40
# Tätä pidemmästä nimestä pudotetaan yleiset toimialasanat ("parturi-kampaamo-taina-lantiainen" -> "taina-lantiainen")
SLUG_GENERIC_DROP_FROM = 24
SLUG_ATTEMPTS = 10
SLUG_RE = re.compile(rf"^[a-z0-9](?:[a-z0-9-]{{0,{SLUG_NAME_MAX - 2}}}[a-z0-9])?-[{SLUG_ALPHABET}]{{{SLUG_SUFFIX_LEN}}}$")

# Yritysmuodot pois aina, toimialasanat vain pitkistä nimistä
_LEGAL_FORMS = {"oy", "oyj", "ab", "ky", "ay", "tmi", "toiminimi", "ltd", "ry"}
_GENERIC_WORDS = {
    "parturi", "kampaamo", "parturikampaamo", "hiusstudio", "hiussalonki", "kauneushoitola", "kauneussalonki",
    "kynsistudio", "hieronta", "ravintola", "kahvila", "pizzeria", "bistro", "autokorjaamo", "korjaamo",
    "autohuolto", "rengasliike", "kukkakauppa", "studio", "salon", "salonki", "palvelut", "palvelu",
}
_TRANSLIT = str.maketrans({"ä": "a", "ö": "o", "å": "a", "ü": "u", "ß": "ss", "æ": "ae", "ø": "o"})


def name_slug(name: str) -> str:
    """Yrityksen nimestä URL-osa: pienet kirjaimet, ääkköset a/o, väliviivat, max SLUG_NAME_MAX merkkiä."""
    text = unicodedata.normalize("NFKC", name).lower().translate(_TRANSLIT)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w and w not in _LEGAL_FORMS]
    if len("-".join(words)) > SLUG_GENERIC_DROP_FROM:
        specific = [w for w in words if w not in _GENERIC_WORDS]
        words = specific or words
    slug = ""
    for word in words:
        candidate = f"{slug}-{word}" if slug else word
        if len(candidate) > SLUG_NAME_MAX:
            break
        slug = candidate
    if not slug and words:
        slug = words[0][:SLUG_NAME_MAX]
    return slug


def random_slug_suffix() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(SLUG_SUFFIX_LEN))


def new_public_slug(
    name: str,
    taken: Callable[[str], bool],
    *,
    suffix: Optional[Callable[[], str]] = None,
) -> str:
    """Uniikki /{nimi}-{satunnainen}. taken(slug) tarkistaa kannasta; törmäyksessä uusi satunnaisosa."""
    base = name_slug(name) or "demo"
    for _ in range(SLUG_ATTEMPTS):
        slug = f"{base}-{(suffix or random_slug_suffix)()}"
        if not taken(slug):
            return slug
    raise RuntimeError(f"Could not allocate a unique demo address after {SLUG_ATTEMPTS} attempts")


def phone_to_tel(phone: Optional[str]) -> Optional[str]:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit() or ch == "+")
    if not digits:
        return None
    if digits.startswith("+"):
        return digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("0"):
        return "+358" + digits[1:]
    return digits


@dataclass(frozen=True)
class DemoBusiness:
    name: str
    city: str
    address: Optional[str]
    phone: Optional[str]
    maps_url: Optional[str]


@dataclass(frozen=True)
class DemoSender:
    name: str
    company_name: Optional[str]
    phone: Optional[str]
    website: Optional[str]


@dataclass(frozen=True)
class HeadingFont:
    family: str
    file: str
    weight: int
    fallback: str


# Yksi otsikkofontti per pohja (OFL, Fontsource 5.3.0, latin-osajoukko kattaa å ä ö), leipäteksti system-ui.
# Upotetaan base64-muodossa: ei ulkoista CDN:ää, demo pysyy yhtenä tiedostona.
TEMPLATE_FONTS: dict[str, HeadingFont] = {
    "beauty": HeadingFont("Cormorant Garamond", "cormorant-garamond-latin-600-normal.woff2", 600, "Georgia, 'Times New Roman', serif"),
    "restaurant": HeadingFont("DM Serif Display", "dm-serif-display-latin-400-normal.woff2", 400, "Georgia, 'Times New Roman', serif"),
    "services": HeadingFont("Manrope", "manrope-latin-700-normal.woff2", 700, "system-ui, -apple-system, 'Segoe UI', sans-serif"),
}


@lru_cache(maxsize=None)
def font_face_css(template: str) -> str:
    font = TEMPLATE_FONTS[template]
    data = base64.b64encode((_TEMPLATE_DIR / "fonts" / font.file).read_bytes()).decode("ascii")
    return (
        f"@font-face{{font-family:'{font.family}';font-style:normal;font-weight:{font.weight};"
        f"font-display:swap;src:url(data:font/woff2;base64,{data}) format('woff2');}}"
    )


@dataclass(frozen=True)
class ImageView:
    src: str
    srcset: str
    credit_name: str
    credit_url: str
    unsplash_url: str


def _image_view(photo: DemoPhoto, widths: tuple[int, ...], utm_app: str, ratio: Optional[float] = None) -> ImageView:
    """ratio = korkeus/leveys: Unsplash rajaa kuvan valmiiksi (pienempi tiedosto kuin CSS-rajaus)."""
    def url(w: int) -> str:
        return photo_url(photo, w, height=round(w * ratio) if ratio else None)

    return ImageView(
        src=url(widths[len(widths) // 2]),
        srcset=", ".join(f"{url(w)} {w}w" for w in widths),
        credit_name=photo.photographer_name,
        credit_url=with_utm(photo.photographer_url, utm_app),
        unsplash_url=unsplash_home_url(utm_app),
    )


# --- Versio 2: erilliset tiedostot ---

ASSET_DIR = _TEMPLATE_DIR / "assets"
SHARED_ASSET_GROUP = "yhteinen"
ASSET_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2"}
ASSET_NAME_RE = re.compile(r"^[a-z0-9-]+\.(css|js|woff2)$")
ASSET_DIGEST_LEN = 10
_CSS_FONT_URL_RE = re.compile(r'url\("([a-z0-9-]+\.woff2)"\)')


@dataclass(frozen=True)
class DemoAsset:
    group: str  # pohjan tunniste tai "yhteinen"
    name: str
    body: bytes
    digest: str  # sisällön SHA-256:n alku: ?v= ja R2-avain, joten muuttunut tiedosto saa uuden osoitteen
    content_type: str

    @property
    def url(self) -> str:
        # Suhteellinen: /demo/{polku} -> /demo/a/..., Workerissa /{polku} -> /a/...
        return f"a/{self.group}/{self.name}?v={self.digest}"


_asset_cache: dict[tuple[str, str], tuple[int, DemoAsset]] = {}


def demo_asset(group: str, name: str) -> Optional[DemoAsset]:
    """Tiedosto paketista, tai None. CSS:n fonttiviittauksiin lisätään fontin ?v=, joten CSS:n tiiviste
    muuttuu myös fontin muuttuessa. Välimuisti tiedoston mtimen mukaan (dev: muokkaus näkyy heti)."""
    if not re.fullmatch(r"[a-z]{2,20}", group) or not ASSET_NAME_RE.fullmatch(name):
        return None
    path = ASSET_DIR / group / name
    if not path.is_file():
        return None
    mtime = path.stat().st_mtime_ns
    cached = _asset_cache.get((group, name))
    if cached and cached[0] == mtime:
        return cached[1]
    body = path.read_bytes()
    if path.suffix == ".css":
        def versioned(match: re.Match[str]) -> str:
            font = demo_asset(group, match.group(1))
            return f'url("{match.group(1)}?v={font.digest}")' if font else match.group(0)
        body = _CSS_FONT_URL_RE.sub(versioned, body.decode("utf-8")).encode("utf-8")
    asset = DemoAsset(
        group=group, name=name, body=body,
        digest=hashlib.sha256(body).hexdigest()[:ASSET_DIGEST_LEN],
        content_type=ASSET_TYPES[path.suffix],
    )
    _asset_cache[(group, name)] = (mtime, asset)
    return asset


def template_assets(template: str) -> list[DemoAsset]:
    """Kaikki tiedostot, joihin version 2 demo voi viitata. Versio 1: tyhjä (kaikki inline)."""
    if TEMPLATES.get(template, TEMPLATES[DEFAULT_TEMPLATE]).version < 2:
        return []
    assets: list[DemoAsset] = []
    for group in (SHARED_ASSET_GROUP, template):
        for path in sorted((ASSET_DIR / group).iterdir()):
            asset = demo_asset(group, path.name)
            if asset is not None:
                assets.append(asset)
    return assets


def is_v2_template(template: str) -> bool:
    return TEMPLATES.get(template, TEMPLATES[DEFAULT_TEMPLATE]).version >= 2


# --- Aukioloajat sivulle ---

_DAY_KEYS = ["su", "ma", "ti", "ke", "to", "pe", "la"]  # Googlen day-numerointi (0 = su)
_DAY_NAMES = ["Sunnuntai", "Maanantai", "Tiistai", "Keskiviikko", "Torstai", "Perjantai", "Lauantai"]
_DAY_SHORT = ["su", "ma", "ti", "ke", "to", "pe", "la"]
CLOSED = "suljettu"


@dataclass(frozen=True)
class WeekRow:
    paiva: int  # 1 = ma ... 7 = su (aukiolo.js: data-paiva)
    label: str
    value: str
    closed: bool


def _clock(hhmm: str) -> str:
    """"07:30" -> "7.30", "10:00" -> "10" (suomalainen tapa)."""
    hour, minute = hhmm.split(":")
    return f"{int(hour)}" if minute == "00" else f"{int(hour)}.{minute}"


def aukiolo_attrs(periods: list[OpeningPeriod]) -> dict[str, str]:
    """{"ma": "10:00-12:00,13:00-17:00", ...} #aukiolo-elementin data-attribuuteiksi. Puuttuva = suljettu."""
    by_day: dict[str, list[str]] = {}
    for p in sorted(periods, key=lambda p: (p.day, p.open)):
        by_day.setdefault(_DAY_KEYS[p.day], []).append(f"{p.open}-{p.close}")
    return {key: ",".join(ranges) for key, ranges in by_day.items()}


def _description_value(line: str) -> tuple[str, str]:
    name, _, value = line.partition(": ")
    return name.strip().lower(), value.strip()


def week_rows(content: DemoStoredContent) -> list[WeekRow]:
    """Kiinteä viikkoaikataulu (näkyy ilman JS:ää). Ensisijaisesti periodseista, vanhoissa demoissa
    Googlen valmiista riveistä. Tyhjä lista = ei aukiolotietoja."""
    rows: list[WeekRow] = []
    if content.opening_periods:
        for paiva in range(1, 8):
            day = paiva % 7
            ranges = [p for p in content.opening_periods if p.day == day]
            if any(p.open == "00:00" and p.close == "24:00" for p in ranges):
                value = "auki koko päivän"
            else:
                value = ", ".join(f"{_clock(p.open)}–{_clock(p.close)}" for p in ranges) or CLOSED
            rows.append(WeekRow(paiva, _DAY_NAMES[day], value, not ranges))
        return rows
    names = {n.lower(): i for i, n in enumerate(_DAY_NAMES)}
    for line in content.opening_hours:
        name, value = _description_value(line)
        day = names.get(name)
        if day is None or not value:
            continue
        closed = value.lower() == CLOSED
        rows.append(WeekRow(day or 7, _DAY_NAMES[day], CLOSED if closed else value, closed))
    return sorted(rows, key=lambda r: r.paiva)


def hours_summary(rows: list[WeekRow]) -> str:
    """Peräkkäiset samat päivät yhteen: "Ma–pe 10–19, la 10–15, su suljettu" (Tänään-rivi ilman JS:ää)."""
    groups: list[tuple[int, int, str]] = []
    for row in rows:
        if groups and groups[-1][2] == row.value and groups[-1][1] == row.paiva - 1:
            groups[-1] = (groups[-1][0], row.paiva, row.value)
        else:
            groups.append((row.paiva, row.paiva, row.value))
    parts = []
    for first, last, value in groups:
        days = _DAY_SHORT[first % 7] if first == last else f"{_DAY_SHORT[first % 7]}–{_DAY_SHORT[last % 7]}"
        parts.append(f"{days} {value}")
    text = ", ".join(parts)
    return text[:1].upper() + text[1:]


def short_address(address: Optional[str]) -> Optional[str]:
    """"Kauppakatu 3, 02700 Kauniainen, Suomi" -> "Kauppakatu 3" (otsikoksi)."""
    if not address:
        return None
    return address.split(",")[0].strip() or None


def address_lines(address: Optional[str]) -> list[str]:
    """Osoite riveiksi ilman maata: ["Kauppakatu 3", "02700 Kauniainen"]."""
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) > 1 and parts[-1].lower() in ("suomi", "finland"):
        parts = parts[:-1]
    return parts


def banner_text(business: DemoBusiness, sender: DemoSender) -> str:
    return f"Tämä on luonnos, jonka {sender.name} teki yritykselle {business.name}. Ei yrityksen virallinen sivu."


def render_demo_html(
    *,
    template: str,
    color_scheme: str,
    content: DemoStoredContent,
    business: DemoBusiness,
    sender: DemoSender,
    utm_app: str = "agency_hunter",
) -> str:
    template, color_scheme = validate_template_choice(template, color_scheme)
    tpl = TEMPLATES[template]
    if tpl.version >= 2:
        return _render_v2(template, color_scheme, content, business, sender, utm_app)
    icons = service_icon_names([(s.name, s.description) for s in content.services], template)
    images = content.images
    return _env.get_template(f"{template}.html.j2").render(
        template=template,
        services_title=tpl.services_title,
        services_lead=tpl.services_lead,
        colors=tpl.schemes[color_scheme],
        font=TEMPLATE_FONTS[template],
        font_face_css=font_face_css(template),
        content=content,
        services=[(s, icon_svg(name)) for s, name in zip(content.services, icons)],
        icon=icon_svg,
        hero_image=_image_view(images.hero, (640, 1080, 1600, 2200), utm_app) if images.hero else None,
        mood_images=[_image_view(p, (480, 800, 1200), utm_app) for p in images.mood],
        business=business,
        sender=sender,
        tel=phone_to_tel(business.phone),
        banner=banner_text(business, sender),
    )


# Kuvien muodot ja leveydet pohjittain: (leveydet, korkeus/leveys). Hero preloadataan.
_V2_HERO: dict[str, tuple[tuple[int, ...], Optional[float]]] = {
    "cafe": ((640, 960, 1280), 1.0),  # pyöreä allas
}
_V2_MOOD: dict[str, tuple[tuple[int, ...], Optional[float]]] = {
    "cafe": ((640, 960, 1280), 1.25),  # 4:5 pystykuvat
}


def _render_v2(
    template: str,
    palette: str,
    content: DemoStoredContent,
    business: DemoBusiness,
    sender: DemoSender,
    utm_app: str,
) -> str:
    tpl = TEMPLATES[template]
    scheme = tpl.schemes[palette]
    assert isinstance(scheme, Palette)

    def asset(group: str, name: str) -> DemoAsset:
        found = demo_asset(group, name)
        if found is None:
            raise RuntimeError(f"Demo asset missing: {group}/{name}")
        return found

    hero_widths, hero_ratio = _V2_HERO[template]
    mood_widths, mood_ratio = _V2_MOOD[template]
    images = content.images
    rows = week_rows(content)
    photos = ([images.hero] if images.hero else []) + list(images.mood)
    return _env.get_template(f"{template}.html.j2").render(
        template=template,
        palette=palette,
        theme_color=scheme.theme,
        tpl=tpl,
        content=content,
        about_title=content.about_title or tpl.about_title,
        asset=asset,
        hero_image=_image_view(images.hero, hero_widths, utm_app, hero_ratio) if images.hero else None,
        mood_images=[_image_view(p, mood_widths, utm_app, mood_ratio) for p in images.mood],
        # Kuvaajat kerran alatunnisteessa (sama kuvaaja voi olla useassa kuvassa)
        credits=list({p.photographer_name: _image_view(p, (640,), utm_app) for p in photos}.values()),
        unsplash_url=unsplash_home_url(utm_app),
        business=business,
        address_lines=address_lines(business.address),
        street=short_address(business.address),
        sender=sender,
        tel=phone_to_tel(business.phone),
        banner=banner_text(business, sender),
        aukiolo=aukiolo_attrs(content.opening_periods),
        week=rows,
        summary=hours_summary(rows) if rows else None,
    )
