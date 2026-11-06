"""Unsplash API -kuvat demosivuille.

Ehdot (API Guidelines / API Terms, tarkistettu 11/2026):
- Hotlinking pakollinen: kuvat ladataan API:n palauttamista photo.urls-osoitteista
  (images.unsplash.com), ixid-parametri säilytetään, w/q/fit/auto ovat sallittuja.
- Attribuutio aina kun kuva näytetään: kuvaaja + linkki profiiliin + Unsplash, utm_source/utm_medium.
- download_location kutsutaan kun kuva otetaan käyttöön (asetetaan sivulle).
- Access Key pysyy palvelimella; demo-HTML ei sisällä avainta.
- Demo-tila 50 pyyntöä/h (kuvien lataus images.unsplash.comista ei kuluta kiintiötä).
"""
import logging
import re
from typing import Optional
from urllib.parse import urlencode

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

API_BASE = "https://api.unsplash.com"
SEARCH_PER_PAGE = 20
MIN_CANDIDATES = 4
MAX_OPTIONS = 8
MOOD_COUNT = 3

# Hero-kuvaan ei tunnistettavia kasvoja jos mahdollista: alt/description-tekstien perusteella
_PEOPLE_RE = re.compile(
    r"\b(person|people|woman|women|man|men|girl|girls|boy|boys|lady|guy|child|children|kid|kids|face|faces|"
    r"portrait|model|smiling|smile|couple|bride|customer|customers|client|clients|barber cutting|hairdresser|"
    r"stylist|hairstylist|selfie)\b",
    re.IGNORECASE,
)

# Hero-kuvaan ei tuotemerkkejä: logot ja tuotehyllyt voivat antaa vaikutelman, että yritys
# käyttää tai myy kyseisiä merkkejä. Tunnistus kuvauksesta, alt-tekstistä ja tageista.
_PRODUCTS_RE = re.compile(
    r"\b(products?|brands?|branded|logos?|labels?|shelf|shelves|shelving|bottles?|cosmetics?|packaging|"
    r"merchandise|retail|shampoos?|conditioners?|skincare|skin care|haircare|hair care products?|jars?|tubes?)\b",
    re.IGNORECASE,
)

# Hakusanat englanniksi (lang-parametri on Unsplashilla beta-ominaisuus, joka vaatii erillisen hakemuksen).
# Avain täsmätään primary_typen alkuun/sisältöön; yrityksen nimellä ei koskaan haeta.
_QUERIES: list[tuple[tuple[str, ...], list[str]]] = [
    (("barber",), ["barbershop interior", "barber tools"]),
    (("nail",), ["nail salon", "manicure"]),
    (("spa", "massage", "sauna"), ["spa interior", "massage stones"]),
    (("beauty", "makeup", "lash", "brow", "beautician"), ["beauty salon interior", "cosmetics"]),
    (("hair", "salon"), ["hair salon interior", "hairdresser tools"]),
    (("cafe", "coffee", "tea"), ["cafe interior", "coffee cup"]),
    (("bakery", "pastry", "cake"), ["bakery pastries", "fresh bread"]),
    (("pizza",), ["pizza oven", "pizza"]),
    (("bar", "pub", "wine"), ["cocktail bar", "wine bar interior"]),
    (("restaurant", "food", "meal", "diner", "bistro"), ["restaurant interior", "plated food"]),
    (("plumb",), ["plumbing tools", "bathroom renovation"]),
    (("electric",), ["electrician tools", "electrical work"]),
    # "car_" eikä "car": muuten osuisi hair_care- ja skin_care-tyyppeihin
    (("car_", "auto_", "tire", "tyre"), ["car workshop", "auto repair garage"]),
    (("clean",), ["cleaning supplies", "clean home interior"]),
    (("dentist", "dental"), ["dental clinic interior"]),
    (("physio", "chiropract"), ["physiotherapy clinic"]),
    (("gym", "fitness"), ["gym interior"]),
    (("florist", "flower"), ["flower shop"]),
    (("painter", "painting"), ["house painting"]),
    (("construction", "contractor", "roofing", "carpenter"), ["carpentry tools", "home renovation"]),
]
_TEMPLATE_FALLBACK_QUERIES = {
    "beauty": ["beauty salon interior", "hair salon interior"],
    "restaurant": ["restaurant interior", "cafe interior"],
    "services": ["small business workspace", "craftsman tools"],
}


class DemoPhoto(BaseModel):
    id: str
    raw_url: str  # photo.urls.raw (sis. ixid); koko ja laatu lisätään parametreina
    alt: str = ""
    photographer_name: str
    photographer_url: str  # user.links.html
    download_location: str
    has_people: bool = False
    has_products: bool = False


def image_queries(primary_type: Optional[str], template: str) -> list[str]:
    t = (primary_type or "").lower()
    for keys, queries in _QUERIES:
        if any(k in t for k in keys):
            return queries
    return _TEMPLATE_FALLBACK_QUERIES.get(template, _TEMPLATE_FALLBACK_QUERIES["services"])


def _headers(access_key: str) -> dict[str, str]:
    return {"Authorization": f"Client-ID {access_key}", "Accept-Version": "v1"}


def _to_photo(item: dict[str, object]) -> Optional[DemoPhoto]:
    try:
        urls = item["urls"]
        user = item["user"]
        links = item["links"]
        assert isinstance(urls, dict) and isinstance(user, dict) and isinstance(links, dict)
        user_links = user.get("links") or {}
        assert isinstance(user_links, dict)
        text = " ".join(str(item.get(k) or "") for k in ("alt_description", "description"))
        tags = item.get("tags") or []
        tag_text = " ".join(str(t.get("title") or "") for t in tags if isinstance(t, dict)) if isinstance(tags, list) else ""
        return DemoPhoto(
            id=str(item["id"]),
            raw_url=str(urls["raw"]),
            alt=str(item.get("alt_description") or ""),
            photographer_name=str(user.get("name") or user.get("username") or "Unsplash"),
            photographer_url=str(user_links["html"]),
            download_location=str(links["download_location"]),
            has_people=bool(_PEOPLE_RE.search(text)),
            has_products=bool(_PRODUCTS_RE.search(f"{text} {tag_text}")),
        )
    except (KeyError, TypeError, AssertionError, ValueError):
        return None


def search_photos(query: str, access_key: str, per_page: int = SEARCH_PER_PAGE) -> list[DemoPhoto]:
    """Yksi /search/photos-kutsu. Virhe -> tyhjä lista (demo käyttää gradienttia)."""
    try:
        r = requests.get(
            f"{API_BASE}/search/photos",
            params={
                "query": query,
                "per_page": min(per_page, 30),
                "orientation": "landscape",
                "content_filter": "high",
            },
            headers=_headers(access_key),
            timeout=10,
        )
        if r.status_code >= 400:
            logger.warning(f"Unsplash search {r.status_code}: {r.text[:200]}")
            return []
        remaining = r.headers.get("X-Ratelimit-Remaining")
        if remaining is not None:
            logger.info(f"Unsplash: '{query}' -> rate limit remaining {remaining}")
        results = r.json().get("results") or []
        return [p for p in (_to_photo(item) for item in results if isinstance(item, dict)) if p is not None]
    except Exception as e:
        logger.warning(f"Unsplash search epäonnistui ('{query}'): {e}")
        return []


def find_candidates(primary_type: Optional[str], template: str, access_key: str) -> list[DemoPhoto]:
    """Enintään 2 hakua: toinen hakusana vain jos ensimmäinen tuotti liian vähän kuvia."""
    seen: set[str] = set()
    candidates: list[DemoPhoto] = []
    for query in image_queries(primary_type, template):
        for photo in search_photos(query, access_key):
            if photo.id not in seen:
                seen.add(photo.id)
                candidates.append(photo)
        if len(candidates) >= MIN_CANDIDATES:
            break
    return candidates


def _hero_rank(photo: DemoPhoto) -> int:
    """0 = ei ihmisiä eikä tuotteita, 1 = ihmisiä, 2 = tuotteita, 3 = molempia. Tuotemerkit ovat pahempia."""
    return (2 if photo.has_products else 0) + (1 if photo.has_people else 0)


def pick_hero(candidates: list[DemoPhoto]) -> Optional[DemoPhoto]:
    """Paras hero-kuva. Jos puhdasta ei ole, käytetään parasta jäljelle jäänyttä ja lokitetaan varoitus."""
    if not candidates:
        return None
    hero = min(candidates, key=_hero_rank)  # min on vakaa: tasatilanteessa hakutuloksen järjestys
    if _hero_rank(hero) > 0:
        reasons = [r for r, flag in (("ihmisiä", hero.has_people), ("tuotteita/merkkejä", hero.has_products)) if flag]
        logger.warning(
            f"Unsplash: ei puhdasta hero-kuvaa {len(candidates)} ehdokkaasta, käytetään parasta jäljelle jäänyttä "
            f"({hero.id}: {', '.join(reasons)})"
        )
    return hero


def choose_images(candidates: list[DemoPhoto]) -> tuple[Optional[DemoPhoto], list[DemoPhoto], list[DemoPhoto]]:
    """(hero, mood, options). Hero: ei ihmisiä eikä tuotemerkkejä jos mahdollista."""
    if not candidates:
        return None, [], []
    hero = pick_hero(candidates)
    assert hero is not None
    # Vaihtoehdot: hero-kelpoisimmat ensin, hero mukaan listaan
    options = sorted(candidates, key=_hero_rank)[:MAX_OPTIONS]
    if hero not in options:
        options = [hero] + options[: MAX_OPTIONS - 1]
    # Tunnelmakuvat samasta listasta kuin vaihtoehdot: hero-vaihto modaalissa pitää muut kuvat johdonmukaisina
    return hero, mood_for(hero, options), options


def mood_for(hero: Optional[DemoPhoto], pool: list[DemoPhoto]) -> list[DemoPhoto]:
    return [p for p in pool if hero is None or p.id != hero.id][:MOOD_COUNT]


def photo_url(photo: DemoPhoto, width: int, *, quality: int = 70) -> str:
    sep = "&" if "?" in photo.raw_url else "?"
    return f"{photo.raw_url}{sep}{urlencode({'w': width, 'q': quality, 'auto': 'format', 'fit': 'crop'})}"


def with_utm(url: str, app_name: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urlencode({'utm_source': app_name, 'utm_medium': 'referral'})}"


def unsplash_home_url(app_name: str) -> str:
    return with_utm("https://unsplash.com/", app_name)


def track_download(photo: DemoPhoto, access_key: str) -> None:
    """Unsplashin vaatima lataustapahtuma kun kuva asetetaan sivulle. Virheet vain lokiin."""
    try:
        r = requests.get(photo.download_location, headers=_headers(access_key), timeout=10)
        if r.status_code >= 400:
            logger.warning(f"Unsplash download tracking {r.status_code} ({photo.id})")
    except Exception as e:
        logger.warning(f"Unsplash download tracking epäonnistui ({photo.id}): {e}")
