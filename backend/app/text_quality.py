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
        ("autamme", r"\bautamme\b"),
        ("tarjoamme laadukasta", r"\btarjoamme\s+laadukk?a\w*"),
        ("tervetuloa huolehtimaan", r"\btervetuloa\s+huolehtima\w*"),
    ]
]
PRICE_RE = re.compile(r"\d[\d\s.,]*\s*(€|e\b|euro)", re.IGNORECASE)


def find_forbidden_words(text: str) -> list[str]:
    return [label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(text)]


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


# Toistotarkistus: sanaparit/-kolmikot, joissa vähintään yksi sisältösana (ei pelkkiä täytesanoja)
_STOPWORDS = {
    "ja", "tai", "on", "ovat", "se", "ne", "että", "myös", "kun", "jos", "niin", "kuin", "sekä", "mutta",
    "me", "te", "teille", "teidän", "meillä", "meiltä", "meidän", "sen", "ei", "olla", "voi", "voitte",
}
_PHRASE_WORD_RE = re.compile(r"[a-zåäöéü]+", re.IGNORECASE)


def repeated_phrases(texts: list[str], *, min_words: int = 2, max_words: int = 4) -> list[str]:
    """Fraasit (2-4 sanaa), jotka esiintyvät sivun teksteissä useammin kuin kerran.

    Palauttaa vain pisimmät: jos "varatkaa aika puhelimitse" toistuu, "varatkaa aika" ei listaudu erikseen.
    """
    counts: dict[tuple[str, ...], int] = {}
    for text in texts:
        words = [w.lower() for w in _PHRASE_WORD_RE.findall(text)]
        for n in range(min_words, max_words + 1):
            for i in range(len(words) - n + 1):
                gram = tuple(words[i:i + n])
                if all(w in _STOPWORDS for w in gram):
                    continue
                counts[gram] = counts.get(gram, 0) + 1
    repeated = [g for g, c in counts.items() if c > 1]
    longest = [
        g for g in repeated
        if not any(len(o) > len(g) and any(o[i:i + len(g)] == g for i in range(len(o) - len(g) + 1)) for o in repeated)
    ]
    return sorted((" ".join(g) for g in longest), key=lambda p: (-len(p.split()), p))
