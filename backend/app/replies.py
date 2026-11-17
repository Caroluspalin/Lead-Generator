"""Vastausten tunnistus IMAPilla: vastaus pysäyttää liidin sarjan, automaattivastaus ei.

Postilaatikkoa luetaan vain luku -tilassa (BODY.PEEK), eikä viestejä merkitä luetuiksi tai poisteta.
"""
from __future__ import annotations

import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from email.utils import parseaddr
from typing import Callable, Optional

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from . import followups
from .models import FollowUpSequence, FollowUpStep, Lead, MailboxState, utc_now
from .utils.smtp_client import tls_context

logger = logging.getLogger(__name__)

IMAP_TIMEOUT_SECONDS = 30
INITIAL_LOOKBACK_DAYS = 14
MAX_MESSAGES_PER_CHECK = 200
MAX_MESSAGE_BYTES = 300_000
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")
_AUTO_SUBJECT_RE = re.compile(
    r"^\s*(auto(matic)?[\s-]*(reply|response)|automaattinen vastaus|automatisk svar|out of office|poissa toimistolta|"
    r"vastaus poissaolosta|autosvar|abwesenheit)",
    re.IGNORECASE,
)
_SYSTEM_SENDER_RE = re.compile(r"^(mailer-daemon|postmaster|no-?reply|do-?not-?reply|bounce[s]?)([+._-].*)?$", re.IGNORECASE)
_UNSUBSCRIBE_RE = re.compile(
    r"^\W*(ei kiitos|ei kiinnosta|ei ole ajankohtaista|ei tarvita|unsubscribe|stop|poista|poistakaa|älkää lähettäkö|"
    r"no thanks|no thank you|not interested|remove me)\b",
    re.IGNORECASE,
)
_QUOTE_CUT_RE = re.compile(r"^(on .+ wrote:|.+ kirjoitti.*:|-{2,}\s*original message|from:|lähettäjä:)", re.IGNORECASE)


@dataclass(frozen=True)
class ImapConfig:
    host: str
    user: str
    password: str
    port: int = 993


@dataclass(frozen=True)
class ParsedMail:
    kind: str  # reply / auto / bounce
    from_addr: str
    subject: str
    ref_ids: tuple[str, ...]
    body_start: str
    unsubscribe: bool
    hard_bounce: bool = False


def parse_mail(raw: bytes) -> ParsedMail:
    msg = message_from_bytes(raw, policy=policy.default)
    from_addr = parseaddr(str(msg.get("From", "")))[1].lower()
    subject = " ".join(str(msg.get("Subject", "")).split())
    refs = tuple(dict.fromkeys(_MESSAGE_ID_RE.findall(f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}")))
    body = _body_start(msg)
    if _is_bounce(msg, from_addr, subject):
        return ParsedMail("bounce", from_addr, subject, refs, body, False, hard_bounce=_is_hard_bounce(raw))
    if is_auto_reply(msg, from_addr, subject):
        return ParsedMail("auto", from_addr, subject, refs, body, False)
    unsub = bool(_UNSUBSCRIBE_RE.match(body)) or bool(_UNSUBSCRIBE_RE.match(subject))
    return ParsedMail("reply", from_addr, subject, refs, body, unsub)


def is_auto_reply(msg: Message, from_addr: str, subject: str) -> bool:
    auto_submitted = str(msg.get("Auto-Submitted", "")).strip().lower()
    if auto_submitted and auto_submitted != "no":
        return True
    if msg.get("X-Autoreply") or msg.get("X-Autorespond") or msg.get("X-Auto-Response-Suppress") or msg.get("List-Id"):
        return True
    if str(msg.get("Precedence", "")).strip().lower() in ("bulk", "auto_reply", "junk", "list"):
        return True
    local = from_addr.split("@", 1)[0]
    return bool(_AUTO_SUBJECT_RE.match(subject) or _SYSTEM_SENDER_RE.match(local))


def _is_bounce(msg: Message, from_addr: str, subject: str) -> bool:
    if msg.get_content_type() == "multipart/report" and "delivery-status" in str(msg.get_param("report-type") or "").lower():
        return True
    local = from_addr.split("@", 1)[0].lower()
    return local in ("mailer-daemon", "postmaster") and bool(
        re.search(r"undeliver|delivery (status|failure)|returned mail|failure notice|ei voitu toimittaa", subject, re.IGNORECASE)
    )


def _is_hard_bounce(raw: bytes) -> bool:
    # Pysyvä virhe: DSN:n Status 5.x.x tai SMTP-vastaus 5xx. Tilapäinen (4.x.x) ei pysäytä sarjaa.
    text = raw.decode("utf-8", "replace")
    return bool(re.search(r"^Status:\s*5\.\d+\.\d+", text, re.MULTILINE | re.IGNORECASE))


def _body_start(msg: Message, limit: int = 400) -> str:
    part = msg.get_body(preferencelist=("plain",)) if isinstance(msg, EmailMessage) else None
    try:
        text = part.get_content() if part is not None else ""
    except (LookupError, UnicodeDecodeError):
        text = ""
    lines: list[str] = []
    for line in str(text).splitlines():
        if line.lstrip().startswith(">") or _QUOTE_CUT_RE.match(line.strip()):
            if lines and not line.lstrip().startswith(">"):
                break
            continue
        lines.append(line)
    return " ".join(" ".join(lines).split())[:limit]


# --- Yhdistäminen liidiin ---

def _sequences_by_message_id(session: Session, ids: tuple[str, ...]) -> list[FollowUpSequence]:
    if not ids:
        return []
    seq_ids = {
        sid for sid in session.exec(
            select(FollowUpStep.sequence_id).where(FollowUpStep.message_id.in_(ids), FollowUpStep.status == "sent")  # type: ignore[attr-defined]
        ).all()
    }
    return [seq for sid in seq_ids if (seq := session.get(FollowUpSequence, sid)) is not None]


def _open_sequences_by_address(session: Session, from_addr: str) -> list[FollowUpSequence]:
    if not from_addr:
        return []
    rows = session.exec(
        select(FollowUpSequence)
        .join(FollowUpStep, FollowUpStep.sequence_id == FollowUpSequence.id)
        .where(
            FollowUpSequence.status.in_(("draft", "active")),  # type: ignore[attr-defined]
            FollowUpStep.step_no == 0,
            FollowUpStep.status == "sent",
            func.lower(FollowUpStep.to_email) == from_addr,
        )
    ).all()
    return list({seq.id: seq for seq in rows}.values())


def _sequences_by_bounce_text(session: Session, raw: bytes, now: datetime) -> list[FollowUpSequence]:
    # DSN sisältää alkuperäisen viestin otsakkeet: etsitään viimeaikaisten lähetysten Message-ID:t tekstistä
    text = raw.decode("utf-8", "replace")
    recent = session.exec(
        select(FollowUpStep).where(
            FollowUpStep.status == "sent", FollowUpStep.sent_at >= now - timedelta(days=30), FollowUpStep.message_id != None  # noqa: E711
        )
    ).all()
    hits = tuple(s.message_id for s in recent if s.message_id and s.message_id in text)
    return _sequences_by_message_id(session, hits)


def _mark_dnc(session: Session, from_addr: str, sequences: list[FollowUpSequence]) -> None:
    lead_ids = {seq.lead_id: seq.user_id for seq in sequences}
    leads = [session.get(Lead, lid) for lid in lead_ids]
    if from_addr:
        leads += list(session.exec(select(Lead).where(func.lower(Lead.email) == from_addr)).all())
    for lead in {lead.id: lead for lead in leads if lead is not None}.values():
        lead.do_not_contact = True
        lead.updated_at = utc_now()
        session.add(lead)
        followups.stop_lead_sequences(session, lead.user_id, lead.id, "opt_out")  # type: ignore[arg-type]


@dataclass(frozen=True)
class Outcome:
    action: str  # replied / opt_out / bounced / ignored
    sequence_ids: tuple[int, ...] = ()


def handle_message(session: Session, raw: bytes, own_address: str, now: Optional[datetime] = None) -> Outcome:
    """Käsittelee yhden saapuneen viestin. Ei commitoi."""
    now = now or utc_now()
    mail = parse_mail(raw)
    if mail.kind == "auto" or (own_address and mail.from_addr == own_address.lower()):
        return Outcome("ignored")
    if mail.kind == "bounce":
        if not mail.hard_bounce:
            return Outcome("ignored")
        sequences = [s for s in _sequences_by_bounce_text(session, raw, now) if s.status in ("draft", "active")]
        for seq in sequences:
            followups.stop_sequence(session, seq, "bounced")
        return Outcome("bounced" if sequences else "ignored", tuple(s.id for s in sequences if s.id is not None))

    sequences = _sequences_by_message_id(session, mail.ref_ids) or _open_sequences_by_address(session, mail.from_addr)
    if mail.unsubscribe:
        # Opt-out merkitsee DNC:ksi myös ilman avointa sarjaa, jos lähettäjä on tunnettu liidin osoite
        _mark_dnc(session, mail.from_addr, sequences)
        return Outcome("opt_out", tuple(s.id for s in sequences if s.id is not None))
    replied = [s for s in sequences if s.status in ("draft", "active", "completed")]
    for seq in replied:
        followups.mark_replied(session, seq, now)
    return Outcome("replied" if replied else "ignored", tuple(s.id for s in replied if s.id is not None))


# --- IMAP ---

@dataclass(frozen=True)
class FetchResult:
    uidvalidity: Optional[int]
    messages: list[tuple[int, bytes]]


def _imap_date(day: datetime) -> str:
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def fetch_new_messages(cfg: ImapConfig, *, last_uid: int, uidvalidity: Optional[int], now: datetime) -> FetchResult:
    """Hakee INBOXin uudet viestit vain luku -tilassa. Virheestä poikkeus (kutsuja lokittaa ilman tunnuksia)."""
    imap = imaplib.IMAP4_SSL(cfg.host, cfg.port, ssl_context=tls_context(), timeout=IMAP_TIMEOUT_SECONDS)
    try:
        imap.login(cfg.user, cfg.password)
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise imaplib.IMAP4.error("INBOX select failed")
        _, validity_data = imap.response("UIDVALIDITY")
        current_validity = int(validity_data[0]) if validity_data and validity_data[0] else None
        if uidvalidity is not None and current_validity != uidvalidity:
            last_uid = 0
        if last_uid:
            _, found = imap.uid("SEARCH", "UID", f"{last_uid + 1}:*")
        else:
            _, found = imap.uid("SEARCH", "SINCE", _imap_date(now - timedelta(days=INITIAL_LOOKBACK_DAYS)))
        uids = sorted(int(u) for u in (found[0] or b"").split() if int(u) > last_uid)[:MAX_MESSAGES_PER_CHECK]
        messages: list[tuple[int, bytes]] = []
        for uid in uids:
            _, data = imap.uid("FETCH", str(uid), f"(BODY.PEEK[]<0.{MAX_MESSAGE_BYTES}>)")
            if data and isinstance(data[0], tuple):
                messages.append((uid, data[0][1]))
        return FetchResult(current_validity, messages)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def check_mailbox(
    engine: Engine,
    cfg: ImapConfig,
    own_address: str,
    *,
    now: Optional[datetime] = None,
    fetch: Callable[..., FetchResult] = fetch_new_messages,
) -> list[Outcome]:
    now = now or utc_now()
    with Session(engine) as session:
        state = session.exec(select(MailboxState).where(MailboxState.account == cfg.user)).first()
        if state is None:
            state = MailboxState(account=cfg.user)
            session.add(state)
            session.commit()
            session.refresh(state)
        result = fetch(cfg, last_uid=state.last_uid, uidvalidity=state.uidvalidity, now=now)
        outcomes: list[Outcome] = []
        if state.uidvalidity is not None and result.uidvalidity != state.uidvalidity:
            state.last_uid = 0
        for uid, raw in result.messages:
            outcomes.append(handle_message(session, raw, own_address, now))
            state.last_uid = max(state.last_uid, uid)
        state.uidvalidity, state.checked_at = result.uidvalidity, now
        session.add(state)
        session.commit()
        return outcomes

