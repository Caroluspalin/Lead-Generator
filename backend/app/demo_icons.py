"""Inline SVG -ikonit demosivujen palveluille (24x24, stroke, currentColor).

Ikoni valitaan palvelun nimen (ja tarvittaessa kuvauksen) avainsanoista. Saman sivun
palvelut saavat eri ikonit: jos osuva ikoni on jo käytössä, käytetään seuraavaa osuvaa
tai pohjan varaikonia.
"""
from markupsafe import Markup

ICONS: dict[str, str] = {
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12"/>',
    "razor": '<path d="M5 3h14l-1.5 7h-11z"/><path d="M9 10v3M15 10v3M12 13v8"/>',
    "palette": '<circle cx="13.5" cy="6.5" r="1"/><circle cx="17.5" cy="10.5" r="1"/><circle cx="8.5" cy="7.5" r="1"/><circle cx="6.5" cy="12.5" r="1"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 1.6-.7 1.6-1.7 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.7 1.7-1.7h2c3 0 5.5-2.5 5.5-5.5C22 6 17.5 2 12 2z"/>',
    "wind": '<path d="M17.7 7.7A2.5 2.5 0 1 1 19.5 12H2"/><path d="M9.6 4.6A2 2 0 1 1 11 8H2"/><path d="M12.6 19.4A2 2 0 1 0 14 16H2"/>',
    "leaf": '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8 0 5.5-4.8 10-10 10Z"/><path d="M2 21c0-3 1.9-5.4 5.1-6C9.5 14.5 12 13 13 12"/>',
    "sparkles": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 3v4M21 5h-4M5 17v4M7 19H3"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "brush": '<path d="m9.06 11.9 8.07-8.06a2.85 2.85 0 1 1 4.03 4.03l-8.06 8.08"/><path d="M7.07 14.94c-1.66 0-3 1.35-3 3.02 0 1.33-2.5 1.52-2 2.02 1.08 1.1 2.49 2.02 4 2.02 2.2 0 4-1.8 4-4.04a3.01 3.01 0 0 0-3-3.02z"/>',
    "flower": '<circle cx="12" cy="12" r="3"/><path d="M12 2a3 3 0 0 1 3 3v2.1M12 2a3 3 0 0 0-3 3v2.1M22 12a3 3 0 0 1-3 3h-2.1M22 12a3 3 0 0 0-3-3h-2.1M12 22a3 3 0 0 1-3-3v-2.1M12 22a3 3 0 0 0 3-3v-2.1M2 12a3 3 0 0 1 3-3h2.1M2 12a3 3 0 0 0 3 3h2.1"/>',
    "smile": '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/>',
    "cup": '<path d="M17 8h1a4 4 0 0 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4z"/><path d="M6 2v2M10 2v2M14 2v2"/>',
    "cake": '<path d="M20 21v-8a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8"/><path d="M4 16s.5-1 2-1 2.5 2 4 2 2.5-2 4-2 2.5 2 4 2 2-1 2-1"/><path d="M2 21h20M7 8v3M12 8v3M17 8v3"/>',
    "utensils": '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3zm0 0v7"/>',
    "wine": '<path d="M8 22h8M7 10h10M12 15v7"/><path d="M12 15a5 5 0 0 0 5-5c0-2-.5-4-2-8H9c-1.5 4-2 6-2 8a5 5 0 0 0 5 5z"/>',
    "bag": '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18M16 10a4 4 0 0 1-8 0"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9z"/>',
    "hammer": '<path d="m15 12-8.4 8.4a2.1 2.1 0 1 1-3-3L12 9"/><path d="M17.6 15 22 10.6M20.9 11.7l-1.3-1.3a2.4 2.4 0 0 1-.7-1.7v-.9l-2.5-2.5a5.6 5.6 0 0 0-4-1.6H9l.9.8a6.2 6.2 0 0 1 2.1 4.6v1.6l2 2h.9a2.4 2.4 0 0 1 1.7.7l1.3 1.3"/>',
    "bolt": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    "droplet": '<path d="M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5S5 13 5 15a7 7 0 0 0 7 7z"/>',
    "car": '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"/><circle cx="7" cy="17" r="2"/><path d="M9 17h6"/><circle cx="17" cy="17" r="2"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "gift": '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7M7.5 8a2.5 2.5 0 0 1 0-5C9 3 12 8 12 8s3-5 4.5-5a2.5 2.5 0 0 1 0 5"/>',
    "home": '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "star": '<path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
    "heart": '<path d="M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.8 0-3 .5-4.5 2-1.5-1.5-2.7-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4 3 5.5l7 7z"/>',
    # Käyttöliittymäikonit (napit)
    "phone": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>',
    "pin": '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
}

# (avainsanojen alut pienillä kirjaimilla, ikoni). Järjestys merkitsee: ensimmäinen osuma voittaa.
ICON_RULES: list[tuple[tuple[str, ...], str]] = [
    (("parta", "parran", "parturi"), "razor"),
    (("leikk", "cut", "trimm"), "scissors"),
    (("väri", "värj", "raid", "sävy", "blond", "balayage", "vaalen"), "palette"),
    (("muotoil", "kampau", "föön", "kihar", "permanent", "styling", "kiharr"), "wind"),
    (("kynsi", "kynne", "manikyyr", "pedikyyr", "geeli"), "sparkles"),
    (("ripsi", "ripse", "kulma"), "eye"),
    (("meik", "ehostus"), "brush"),
    (("hieron", "spa", "kasvo", "ihonhoi", "rentoutu"), "flower"),
    (("hoito", "hoid", "tehohoi"), "leaf"),
    (("lapsi", "lasten", "junior"), "smile"),
    (("kahvi", "espresso", "latte", "cappuccino", "teetä", "teelaj"), "cup"),
    (("leivon", "kakku", "pulla", "leipä", "leipo", "croissant", "jälkiruo", "makea"), "cake"),
    (("viini", "olut", "juoma", "cocktail", "drinkki"), "wine"),
    (("nouto", "take away", "kotiinkulj", "catering", "pitopalv"), "bag"),
    (("lounas", "ruoka", "annos", "menu", "illalli", "pizza", "keitto", "salaat", "brunssi", "aamiai"), "utensils"),
    (("korja", "huolto", "vika"), "wrench"),
    (("asenn", "remont", "rakenn", "puusepp"), "hammer"),
    (("sähk",), "bolt"),
    (("putki", "lvi", "vesi", "viemär"), "droplet"),
    # Ei pelkkää "auto": osuisi sanaan "autamme"
    (("auton", "autoj", "autok", "autoh", "autot", "rengas", "renkai", "katsastus"), "car"),
    (("siivo", "puhdist"), "sparkles"),
    (("neuvo", "konsult", "suunnit", "kartoitus"), "chat"),
    (("ajanvar", "varau"), "calendar"),
    (("lahja",), "gift"),
    (("koti", "kiinteist"), "home"),
]

FALLBACK_POOLS: dict[str, list[str]] = {
    "beauty": ["sparkles", "leaf", "heart", "star", "flower", "smile"],
    "restaurant": ["utensils", "cup", "wine", "cake", "star", "heart"],
    "services": ["check", "star", "wrench", "chat", "calendar", "home"],
}


def _matches(text: str) -> list[str]:
    words = text.lower().split()
    found: list[str] = []
    for prefixes, icon in ICON_RULES:
        if any(w.startswith(p) or (" " in p and p in text.lower()) for w in words for p in prefixes):
            if icon not in found:
                found.append(icon)
    return found


def service_icon_names(services: list[tuple[str, str]], template: str) -> list[str]:
    """[(nimi, kuvaus)] -> ikoninimet, eri ikoni jokaiselle palvelulle."""
    used: set[str] = set()
    result: list[str] = []
    pool = FALLBACK_POOLS.get(template, FALLBACK_POOLS["services"])
    for name, description in services:
        candidates = _matches(name) + _matches(description) + pool + list(ICONS)
        icon = next(c for c in candidates if c not in used and c not in ("phone", "pin", "clock"))
        used.add(icon)
        result.append(icon)
    return result


def icon_svg(name: str) -> Markup:
    # Vain omista vakioista -> turvallinen merkitä Markupiksi (Jinja autoescape ei koske)
    return Markup(ICONS[name])
