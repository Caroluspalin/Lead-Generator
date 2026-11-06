"""Demonettisivun generointi liidille.

AI ei kirjoita HTML:ää: se tuottaa vain sisällön JSON-muodossa (DemoAIContent), joka validoidaan
tiukasti. HTML renderöidään valmiista Jinja2-pohjasta (autoescape), joten jokainen demo on
teknisesti toimiva, nopea, mobiiliystävällinen ja turvallinen (ei JavaScriptiä, ei ulkoisia resursseja).
"""
import base64
import json
import logging
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

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
class DemoTemplate:
    label: str
    services_title: str
    services_lead: str  # kiinteä teksti; mukana toistotarkistuksessa
    schemes: dict[str, ColorScheme]


# Värit valittu niin, että tekstin kontrasti taustaa vasten on vähintään WCAG AA (4.5:1)
TEMPLATES: dict[str, DemoTemplate] = {
    "beauty": DemoTemplate(
        label="Hair & beauty",
        services_title="Palvelut",
        services_lead="Varatkaa aika puhelimitse.",
        schemes={
            "rose": ColorScheme("Rose", "#fdf7f7", "#ffffff", "#2b1d21", "#5f4b52", "#9d2f55", "#ffffff", "#5b1a33", "#9d2f55", "#ffffff"),
            "sage": ColorScheme("Sage", "#f6f8f5", "#ffffff", "#1f2a22", "#4d5a50", "#3f6b4f", "#ffffff", "#24412f", "#4f7d60", "#ffffff"),
            "noir": ColorScheme("Noir", "#f7f6f4", "#ffffff", "#1c1b1a", "#55524e", "#1c1b1a", "#ffffff", "#111111", "#3a3632", "#ffffff"),
        },
    ),
    "restaurant": DemoTemplate(
        label="Restaurant & café",
        services_title="Mitä tarjoamme",
        services_lead="Tutustukaa valikoimaamme.",
        schemes={
            "terracotta": ColorScheme("Terracotta", "#fbf6f1", "#ffffff", "#2a1f18", "#5e5048", "#a2452a", "#ffffff", "#6b2a17", "#a2452a", "#ffffff"),
            "olive": ColorScheme("Olive", "#f8f8f2", "#ffffff", "#24261b", "#55584a", "#5b6327", "#ffffff", "#353a15", "#5b6327", "#ffffff"),
            "night": ColorScheme("Night", "#f4f5f8", "#ffffff", "#161a24", "#4b5262", "#2e3a70", "#ffffff", "#121831", "#2e3a70", "#ffffff"),
        },
    ),
    "services": DemoTemplate(
        label="General services",
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
_RESTAURANT_TYPES = ("restaurant", "cafe", "coffee", "bakery", "bar", "pub", "pizza", "food", "meal", "diner", "bistro", "deli", "ice_cream", "tea")


def template_for_primary_type(primary_type: Optional[str]) -> str:
    t = (primary_type or "").lower()
    if any(k in t for k in _BEAUTY_TYPES):
        return "beauty"
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
    return [
        {
            "id": tid,
            "label": t.label,
            "color_schemes": [{"id": sid, "label": s.label} for sid, s in t.schemes.items()],
        }
        for tid, t in TEMPLATES.items()
    ]


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


class DemoStoredContent(DemoContent):
    # Haettu Place Detailsista generoinnin hetkellä; osa demoa, ei erillistä Places-välimuistia
    opening_hours: list[str] = Field(default_factory=list, max_length=7)
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
        if not field.endswith(".name") and field != "hero_title":
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
    for s in content.services:
        texts.extend([s.name, s.description])
    return texts


def find_repeated_phrases(content: DemoAIContent, *, business_name: str, template: str) -> list[str]:
    return repeated_phrases(page_texts(content, business_name=business_name, template=template))


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
  "hero_title": "lyhyt yläotsikko yrityksen nimen yläpuolella, 5-60 merkkiä, EI saa toistaa yrityksen nimen sanoja, esim. Hiukset kuntoon Kauniaisissa",
  "hero_subtitle": "yksi lyhyt, luonteva lause siitä mitä yritys tarjoaa, 10-120 merkkiä",
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

def fetch_opening_hours(place_id: str, api_key: str) -> Optional[list[str]]:
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
        hours = (r.json().get("regularOpeningHours") or {}).get("weekdayDescriptions") or []
        return [str(h)[:80] for h in hours][:7] or None
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


def _image_view(photo: DemoPhoto, widths: tuple[int, ...], utm_app: str) -> ImageView:
    return ImageView(
        src=photo_url(photo, widths[len(widths) // 2]),
        srcset=", ".join(f"{photo_url(photo, w)} {w}w" for w in widths),
        credit_name=photo.photographer_name,
        credit_url=with_utm(photo.photographer_url, utm_app),
        unsplash_url=unsplash_home_url(utm_app),
    )


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
