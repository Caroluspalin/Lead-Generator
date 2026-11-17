"""Tarjous: summat, sisältötiiviste ja tarjoussivun renderöinti.

Hinnat tulevat vain palvelukatalogista (kopioidaan riveille tarjousta luotaessa). Summat lasketaan
kokonaissenteissä ja alv pyöristetään rivi kerrallaan (puolet ylöspäin), jotta sivun summa on aina
sama kuin riviensä summa. Sivu (quotes/<token>.html R2:ssa) palvellaan Workerilla osoitteessa /q/<token>;
Worker kirjoittaa hyväksynnän R2:een (acceptances/<token>.json), ja backend hakee sen.
"""
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

QUOTE_PATH_PREFIX = "q/"
QUOTE_PREFIX = "quotes/"
ACCEPTANCE_PREFIX = "acceptances/"
# Avausavain opens/q-<token>/...: eri nimiavaruus kuin demojen opens/<slug|token>/...
OPEN_PATH_PREFIX = "q-"
ACCEPT_START = "<!--ACCEPT-START-->"
ACCEPT_END = "<!--ACCEPT-END-->"
MAX_LINES = 30
MAX_QUANTITY = 1000
MAX_UNIT_PRICE_CENTS = 100_000_000
MAX_VAT_BP = 10_000


def quote_object_key(token: str) -> str:
    return f"{QUOTE_PREFIX}{token}.html"


def acceptance_key(token: str) -> str:
    return f"{ACCEPTANCE_PREFIX}{token}.json"


def open_path(token: str) -> str:
    return f"{OPEN_PATH_PREFIX}{token}"


@dataclass(frozen=True)
class LineInput:
    name: str
    description: Optional[str]
    unit_price_cents: int
    quantity: int
    vat_rate_bp: int


@dataclass(frozen=True)
class Totals:
    net_cents: int
    vat_cents: int
    gross_cents: int
    # alv-kanta (bp) -> (veroton, alv)
    by_rate: dict[int, tuple[int, int]]


def line_net(line: LineInput) -> int:
    return line.unit_price_cents * line.quantity


def line_vat(line: LineInput) -> int:
    return (line_net(line) * line.vat_rate_bp + 5000) // 10_000


def compute_totals(lines: Sequence[LineInput]) -> Totals:
    by_rate: dict[int, tuple[int, int]] = {}
    net = vat = 0
    for line in lines:
        n, v = line_net(line), line_vat(line)
        net += n
        vat += v
        prev_n, prev_v = by_rate.get(line.vat_rate_bp, (0, 0))
        by_rate[line.vat_rate_bp] = (prev_n + n, prev_v + v)
    return Totals(net_cents=net, vat_cents=vat, gross_cents=net + vat, by_rate=dict(sorted(by_rate.items())))


def deal_value_euros(net_cents: int) -> int:
    """Liidin deal_value on kokonaisia euroja: alviton summa pyöristettynä lähimpään euroon."""
    return (net_cents + 50) // 100


def content_hash(
    *, version: int, recipient: str, seller: dict[str, Optional[str]], lines: Sequence[LineInput],
    totals: Totals, terms: Optional[str], valid_until: datetime,
) -> str:
    """SHA-256 siitä sisällöstä, jonka asiakas näkee. Worker tallentaa tiivisteen hyväksynnän mukaan."""
    payload = {
        "version": version,
        "recipient": recipient,
        "seller": seller,
        "lines": [
            [l.name, l.description, l.unit_price_cents, l.quantity, l.vat_rate_bp] for l in lines
        ],
        "net": totals.net_cents,
        "vat": totals.vat_cents,
        "gross": totals.gross_cents,
        "terms": terms,
        "valid_until": valid_until.isoformat(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def format_eur(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    euros, rest = divmod(abs(cents), 100)
    return f"{sign}{euros:,}".replace(",", " ") + f",{rest:02d} €"


def format_rate(bp: int) -> str:
    whole, frac = divmod(bp, 100)
    return f"{whole},{frac:02d}".rstrip("0").rstrip(",") + " %"


def format_date(value: datetime) -> str:
    return f"{value.day}.{value.month}.{value.year}"


_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates" / "quote")),
    autoescape=select_autoescape(["html", "j2"], default=True),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["eur"] = format_eur
_env.filters["rate"] = format_rate


def render_quote_html(
    *, seller: dict[str, Optional[str]], recipient: str, version: int, sent_at: datetime, valid_until: datetime,
    lines: Sequence[LineInput], totals: Totals, terms: Optional[str], digest: str, superseded: bool = False,
) -> str:
    rows = [
        {"line": l, "net": line_net(l), "vat": line_vat(l)} for l in lines
    ]
    return _env.get_template("quote.html.j2").render(
        seller=seller, recipient=recipient, version=version, sent=format_date(sent_at),
        valid_until=format_date(valid_until), rows=rows, totals=totals, terms=terms, digest=digest,
        superseded=superseded, accept_start=ACCEPT_START, accept_end=ACCEPT_END,
    )


@dataclass(frozen=True)
class AcceptanceRecord:
    name: str
    accepted_at: datetime
    signature: str


SIGNATURE_PREFIX = "data:image/png;base64,"
MAX_SIGNATURE_CHARS = 300_000


def parse_acceptance(raw: bytes, expected_hash: Optional[str]) -> Optional[AcceptanceRecord]:
    """Workerin kirjoittama acceptances/<token>.json. None jos muoto, tiiviste tai valtuusvahvistus ei täsmää."""
    try:
        data = json.loads(raw.decode("utf-8"))
        name = str(data["name"]).strip()
        accepted_at = datetime.fromisoformat(str(data["accepted_at"]).replace("Z", "+00:00"))
        signature = str(data["signature"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("authority") is not True:
        return None
    if not expected_hash or data.get("content_hash") != expected_hash:
        return None
    if not 1 <= len(name) <= 100 or not signature.startswith(SIGNATURE_PREFIX) or len(signature) > MAX_SIGNATURE_CHARS:
        return None
    return AcceptanceRecord(name=name, accepted_at=accepted_at, signature=signature)
