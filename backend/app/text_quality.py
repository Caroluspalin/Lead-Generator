"""Generoidun suomenkielisen tekstin laatuvahti (sähköpostit, puhelinskriptit, demosivut)."""
import re

# Kielletyt sanat/fraasit: (näytettävä nimi, regex). Taivutusmuodot mukana; "ihan" ei osu "ihana"-kuvioon.
FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in [
        ("ihana", r"\bihan(a|aa|an|at|ia|ista|imp)\w*"),
        ("upea", r"\bupe(a|i)\w*"),
        ("mahtava", r"\bmahtav\w*"),
        ("ainutlaatuinen", r"\bainutlaatui\w*"),
        ("intohimo", r"\bintohimo\w*"),
        ("ratkaisu", r"\bratkaisu\w*"),
        ("kokonaisvaltainen", r"\bkokonaisvaltai\w*"),
        ("digitaalinen läsnäolo", r"\bdigitaali\w*\s+läsnäolo\w*"),
        ("nostaa seuraavalle tasolle", r"\b(seuraavalle|uudelle)\s+tasolle\b"),
        ("innovatiivinen", r"\binnovatiivi\w*"),
        ("räätälöity", r"\bräätälöi\w*"),
        ("huippu", r"\bhuippu\w*"),
        ("saumaton", r"\bsaumat\w*"),
        ("synergia", r"\bsynergi\w*"),
        ("keskustella tarkemmin", r"\bkeskustel\w*\s+(asiasta\s+)?tarkemmin\b"),
        ("liiketoiminnan kasvu", r"\bliiketoimin\w*\s+kasv\w*"),
        ("saattaa (arvailu)", r"\bsaatta(a|vat|isi)\b"),
    ]
]
PRICE_RE = re.compile(r"\d[\d\s.,]*\s*(€|e\b|euro)", re.IGNORECASE)


def find_forbidden_words(text: str) -> list[str]:
    return [label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(text)]


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))
