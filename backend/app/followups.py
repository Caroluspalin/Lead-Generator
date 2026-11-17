"""Seurantaviestisarjat: aikataulu, lähetysikkuna ja idempotentti lähettäjä.

Mitään ei lähde ilman hyväksyttyä sarjaa (status active). Lähettäjä lukitsee askeleen tilasiirtymällä
scheduled -> sending ennen SMTP-kutsua; jumiutunut sending ei koskaan lähde uudelleen automaattisesti.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.message import Message
from email.utils import make_msgid
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, update
from sqlmodel import Session, select

from .models import (
    OPEN_SEQUENCE_STATUSES,
    FollowUpSequence,
    FollowUpStep,
    Lead,
    utc_now,
)
from .utils.smtp_client import SmtpConfig, SmtpFailure, build_message, send_mail

logger = logging.getLogger(__name__)

HELSINKI = ZoneInfo("Europe/Helsinki")
SEND_START_HOUR = 9
SEND_END_HOUR = 16  # klo 16:00 ei enää lähetetä
# Seurantaviestien päivät aloitusviestistä
STEP_OFFSET_DAYS: dict[int, int] = {1: 3, 2: 8}
FINAL_STEP_NO = max(STEP_OFFSET_DAYS)
STALE_SENDING_AFTER = timedelta(minutes=10)
MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=15)
MIN_GAP_AFTER_PREVIOUS = timedelta(days=2)


@dataclass(frozen=True)
class FollowUpSettings:
    send_enabled: bool = False
    daily_limit: int = 20
    min_delay_seconds: int = 90
    late_grace_days: int = 2

    @classmethod
    def from_env(cls) -> "FollowUpSettings":
        def _int(name: str, default: int) -> int:
            try:
                return max(0, int(os.getenv(name, str(default))))
            except ValueError:
                return default

        return cls(
            send_enabled=os.getenv("FOLLOWUPS_SEND_ENABLED", "false").strip().lower() == "true",
            daily_limit=_int("FOLLOWUPS_DAILY_LIMIT", 20),
            min_delay_seconds=_int("FOLLOWUPS_MIN_DELAY_SECONDS", 90),
            late_grace_days=_int("FOLLOWUPS_LATE_GRACE_DAYS", 2),
        )


# --- Aikataulu ---

def _easter(year: int) -> date:
    # Anonyymi gregoriaaninen algoritmi
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month, day = divmod(h + el - 7 * m + 114, 31)
    return date(year, month, day + 1)


def finnish_holidays(year: int) -> frozenset[date]:
    easter = _easter(year)
    # Juhannusaatto on perjantai 19.-25.6.
    midsummer_eve = next(date(year, 6, d) for d in range(19, 26) if date(year, 6, d).weekday() == 4)
    return frozenset({
        date(year, 1, 1), date(year, 1, 6),
        easter - timedelta(days=2), easter, easter + timedelta(days=1),
        date(year, 5, 1), easter + timedelta(days=39), easter + timedelta(days=49),
        midsummer_eve, midsummer_eve + timedelta(days=1),
        date(year, 12, 6), date(year, 12, 24), date(year, 12, 25), date(year, 12, 26),
    })


def is_send_day(day: date) -> bool:
    return day.weekday() < 5 and day not in finnish_holidays(day.year)


def in_send_window(now: datetime) -> bool:
    local = now.astimezone(HELSINKI)
    return is_send_day(local.date()) and SEND_START_HOUR <= local.hour < SEND_END_HOUR


def next_send_day(day: date) -> date:
    while not is_send_day(day):
        day += timedelta(days=1)
    return day


def _at_window_start(day: date) -> datetime:
    return datetime.combine(day, time(SEND_START_HOUR), tzinfo=HELSINKI).astimezone(timezone.utc)


def step_due_at(first_sent_at: datetime, step_no: int) -> datetime:
    """Aloitusviestin lähetyspäivä + 3 / 8 päivää, siirrettynä seuraavaan lähetyspäivään klo 9 Suomen aikaa."""
    base = first_sent_at.astimezone(HELSINKI).date() + timedelta(days=STEP_OFFSET_DAYS[step_no])
    return _at_window_start(next_send_day(base))


def rescheduled_due_at(now: datetime, previous_sent_at: datetime) -> datetime:
    """Myöhästyneen askeleen uusi aika: aikaisintaan huomenna ja vähintään 2 päivää edellisen viestin jälkeen."""
    earliest = max(
        now.astimezone(HELSINKI).date() + timedelta(days=1),
        (previous_sent_at + MIN_GAP_AFTER_PREVIOUS).astimezone(HELSINKI).date(),
    )
    return _at_window_start(next_send_day(earliest))


def helsinki_day_start(now: datetime) -> datetime:
    local = now.astimezone(HELSINKI)
    return datetime.combine(local.date(), time(0), tzinfo=HELSINKI).astimezone(timezone.utc)


def unsubscribe_headers(from_addr: str) -> dict[str, str]:
    # Vain mailto: backend on paikallinen, joten julkista HTTPS-osoitetta ei ole. IMAP-silmukka tunnistaa viestin.
    return {"List-Unsubscribe": f"<mailto:{from_addr}?subject=unsubscribe>"}


# --- Sarjan tilasiirtymät (eivät commitoi) ---

def open_sequence(session: Session, user_id: str, lead_id: int) -> Optional[FollowUpSequence]:
    return session.exec(
        select(FollowUpSequence)
        .where(
            FollowUpSequence.user_id == user_id,
            FollowUpSequence.lead_id == lead_id,
            FollowUpSequence.status.in_(OPEN_SEQUENCE_STATUSES),  # type: ignore[attr-defined]
        )
        .order_by(FollowUpSequence.id.desc())  # type: ignore[attr-defined]
    ).first()


def sequence_steps(session: Session, sequence: FollowUpSequence) -> list[FollowUpStep]:
    return list(session.exec(
        select(FollowUpStep)
        .where(FollowUpStep.sequence_id == sequence.id, FollowUpStep.user_id == sequence.user_id)
        .order_by(FollowUpStep.step_no)  # type: ignore[arg-type]
    ).all())


def _stop_pending_steps(steps: list[FollowUpStep], session: Session) -> None:
    for step in steps:
        if step.status in ("scheduled", "needs_review") and step.step_no > 0:
            step.status = "stopped"
            session.add(step)


def stop_sequence(session: Session, sequence: FollowUpSequence, reason: str, *, status: str = "stopped") -> None:
    sequence.status = status
    sequence.stop_reason = reason
    sequence.updated_at = utc_now()
    session.add(sequence)
    _stop_pending_steps(sequence_steps(session, sequence), session)


def stop_lead_sequences(session: Session, user_id: str, lead_id: int, reason: str) -> int:
    count = 0
    while (seq := open_sequence(session, user_id, lead_id)) is not None:
        stop_sequence(session, seq, reason)
        session.flush()
        count += 1
    return count


def mark_replied(session: Session, sequence: FollowUpSequence, now: datetime) -> None:
    sequence.replied_at = now
    stop_sequence(session, sequence, "replied", status="replied")


def schedule_steps(session: Session, sequence: FollowUpSequence) -> None:
    """Laskee due_at:t aloitusviestin lähetysajasta. Ilman lähetettyä askelta 0 aikoja ei vielä ole."""
    steps = sequence_steps(session, sequence)
    first = next((s for s in steps if s.step_no == 0 and s.status == "sent" and s.sent_at), None)
    if first is None or first.sent_at is None:
        return
    for step in steps:
        if step.status == "scheduled" and step.due_at is None and step.step_no in STEP_OFFSET_DAYS:
            step.due_at = step_due_at(first.sent_at, step.step_no)
            session.add(step)


def approve_sequence(session: Session, sequence: FollowUpSequence, now: datetime) -> None:
    sequence.status = "active"
    sequence.approved_at = now
    sequence.updated_at = now
    session.add(sequence)
    session.flush()
    schedule_steps(session, sequence)


def record_initial_send(
    session: Session,
    lead: Lead,
    *,
    to: str,
    subject: str,
    body: str,
    message_id: str,
    now: datetime,
    model: str = "",
) -> FollowUpSequence:
    """Tallentaa lähetetyn aloitusviestin sarjan askeleeksi 0 (myös käsin lähetetyn). Ei commitoi."""
    sequence = open_sequence(session, lead.user_id, lead.id)  # type: ignore[arg-type]
    if sequence is not None:
        existing = [s for s in sequence_steps(session, sequence) if s.step_no == 0 and s.status == "sent"]
        if existing:
            # Uusi käsin lähetetty aloitus aloittaa sarjan alusta: vanha ei saa jatkua rinnalla
            stop_sequence(session, sequence, "resent")
            session.flush()
            sequence = None
    if sequence is None:
        sequence = FollowUpSequence(user_id=lead.user_id, lead_id=lead.id)  # type: ignore[arg-type]
        session.add(sequence)
        session.flush()
    step0 = next((s for s in sequence_steps(session, sequence) if s.step_no == 0), None)
    if step0 is None:
        step0 = FollowUpStep(user_id=lead.user_id, sequence_id=sequence.id, lead_id=lead.id, step_no=0, subject=subject, body=body)  # type: ignore[arg-type]
    step0.subject, step0.body, step0.model = subject, body, model
    step0.to_email, step0.message_id = to, message_id
    step0.status, step0.sent_at, step0.due_at = "sent", now, now
    session.add(step0)
    for step in sequence_steps(session, sequence):
        if step.step_no > 0 and step.status == "scheduled":
            step.subject = _reply_subject(step0)
            session.add(step)
    if lead.pipeline_status == "Shortlisted":
        lead.pipeline_status = "Contacted"
        lead.updated_at = now
        session.add(lead)
    session.flush()
    if sequence.status == "active":
        schedule_steps(session, sequence)
    return sequence


# --- Lähettäjä ---

def sent_today(session: Session, user_id: str, now: datetime) -> int:
    # sending lasketaan mukaan: lukittu viesti on jo (mahdollisesti) lähtenyt
    return session.exec(
        select(func.count(FollowUpStep.id)).where(
            FollowUpStep.user_id == user_id,
            FollowUpStep.status.in_(("sent", "sending")),  # type: ignore[attr-defined]
            func.coalesce(FollowUpStep.sent_at, FollowUpStep.claimed_at) >= helsinki_day_start(now),
        )
    ).one()


def recover_stale(session: Session, now: datetime) -> int:
    """Jumiutunut sending (backend kaatui SMTP:n aikana) -> needs_review. Ei koskaan automaattista uudelleenlähetystä."""
    stale = session.exec(
        select(FollowUpStep).where(FollowUpStep.status == "sending", FollowUpStep.claimed_at < now - STALE_SENDING_AFTER)
    ).all()
    for step in stale:
        step.status = "needs_review"
        step.last_error = "Interrupted while sending: check the Sent folder before sending again"
        session.add(step)
    if stale:
        session.commit()
    return len(stale)


@dataclass(frozen=True)
class SenderDeps:
    smtp: SmtpConfig
    from_name: str = ""
    bcc: str = ""
    send: Callable[..., None] = send_mail
    # Onko demolinkki yhä voimassa (korvataan main.py:ssä get_published_demo-tarkistuksella)
    demo_ok: Callable[[Session, Lead, str], bool] = lambda _s, _l, _u: True


def _claim(session: Session, step: FollowUpStep, message_id: str, now: datetime) -> bool:
    result = session.execute(
        update(FollowUpStep)
        .where(FollowUpStep.id == step.id, FollowUpStep.status == "scheduled")  # type: ignore[arg-type]
        .values(status="sending", claimed_at=now, message_id=message_id, attempts=FollowUpStep.attempts + 1)
    )
    session.commit()
    return result.rowcount == 1  # type: ignore[attr-defined]


def _reply_subject(first: FollowUpStep) -> str:
    base = first.subject
    while base.lower().startswith("re:"):
        base = base[3:].strip()
    return f"Re: {base}"


def _blocked_recipient(session: Session, user_id: str, to: str) -> bool:
    return session.exec(
        select(Lead.id).where(Lead.user_id == user_id, Lead.do_not_contact == True, func.lower(Lead.email) == to.lower())  # noqa: E712
    ).first() is not None


def run_once(engine: Engine, now: datetime, settings: FollowUpSettings, deps: SenderDeps) -> Optional[int]:
    """Lähettää enintään yhden erääntyneen viestin. Palauttaa lähetetyn askeleen id:n tai None."""
    if not settings.send_enabled:
        return None
    with Session(engine) as session:
        recover_stale(session, now)
        if not in_send_window(now):
            return None
        last = session.exec(select(func.max(FollowUpStep.sent_at))).one()
        if last is not None and now - last < timedelta(seconds=settings.min_delay_seconds):
            return None
        if session.exec(select(FollowUpStep.id).where(FollowUpStep.status == "sending")).first() is not None:
            return None
        due = session.exec(
            select(FollowUpStep)
            .where(FollowUpStep.status == "scheduled", FollowUpStep.due_at != None, FollowUpStep.due_at <= now, FollowUpStep.step_no > 0)  # noqa: E711
            .order_by(FollowUpStep.due_at, FollowUpStep.id)  # type: ignore[arg-type]
        ).all()
        for step in due:
            claim = _prepare_and_claim(session, step, now, settings, deps)
            if claim is not None:
                _deliver(session, step, claim, now, deps)
                return step.id
    return None


@dataclass(frozen=True)
class _Claim:
    first: FollowUpStep
    to: str
    message_id: str


def _prepare_and_claim(
    session: Session, step: FollowUpStep, now: datetime, settings: FollowUpSettings, deps: SenderDeps
) -> Optional[_Claim]:
    sequence = session.get(FollowUpSequence, step.sequence_id)
    lead = session.get(Lead, step.lead_id)
    if sequence is None or sequence.status != "active" or sequence.user_id != step.user_id:
        return None
    if lead is None or lead.user_id != step.user_id:
        stop_sequence(session, sequence, "manual")
        session.commit()
        return None
    if lead.do_not_contact:
        stop_sequence(session, sequence, "dnc")
        session.commit()
        return None
    steps = {s.step_no: s for s in sequence_steps(session, sequence)}
    previous, first = steps.get(step.step_no - 1), steps.get(0)
    if previous is None or previous.status != "sent" or previous.sent_at is None or first is None:
        return None
    to = (first.to_email or lead.email or "").strip()
    if not to or _blocked_recipient(session, step.user_id, to):
        step.status, step.last_error = "failed", "No usable recipient address"
        session.add(step)
        session.commit()
        return None
    if step.demo_url and not deps.demo_ok(session, lead, step.demo_url):
        step.status, step.last_error = "needs_review", "The demo linked in this message is no longer published"
        session.add(step)
        session.commit()
        return None
    if step.due_at is not None and now - step.due_at > timedelta(days=settings.late_grace_days):
        step.due_at = rescheduled_due_at(now, previous.sent_at)
        session.add(step)
        session.commit()
        return None
    if sent_today(session, step.user_id, now) >= settings.daily_limit:
        return None
    domain = deps.smtp.from_addr.rsplit("@", 1)[-1] if "@" in deps.smtp.from_addr else None
    message_id = make_msgid(domain=domain)
    if not _claim(session, step, message_id, now):
        return None
    session.refresh(step)
    return _Claim(first=first, to=to, message_id=message_id)


def _deliver(session: Session, step: FollowUpStep, claim: _Claim, now: datetime, deps: SenderDeps) -> None:
    first = claim.first
    sequence = session.get(FollowUpSequence, step.sequence_id)
    sent_ids = [s.message_id for s in sequence_steps(session, sequence) if s.status == "sent" and s.message_id] if sequence else []
    headers = {
        **unsubscribe_headers(deps.smtp.from_addr),
        "In-Reply-To": first.message_id or "",
        "References": " ".join(sent_ids),
    }
    headers = {k: v for k, v in headers.items() if v}
    msg: Message = build_message(
        deps.smtp.from_addr, claim.to, _reply_subject(first), step.body, from_name=deps.from_name,
        message_id=claim.message_id, headers=headers,
    )
    try:
        deps.send(deps.smtp, msg, bcc=deps.bcc)
    except SmtpFailure as failure:
        _handle_failure(session, step, failure, now)
        return
    except Exception as exc:  # tuntematon virhe: viesti on voinut lähteä
        logger.error(f"Seurantaviestin {step.id} lähetys päättyi odottamattomaan virheeseen: {type(exc).__name__}")
        _finish(session, step, "needs_review", f"Unexpected error ({type(exc).__name__}): check the Sent folder")
        return
    session.execute(
        update(FollowUpStep)
        .where(FollowUpStep.id == step.id, FollowUpStep.status == "sending")  # type: ignore[arg-type]
        .values(status="sent", sent_at=now, last_error=None)
    )
    session.commit()
    session.refresh(step)
    if step.step_no >= FINAL_STEP_NO:
        sequence = session.get(FollowUpSequence, step.sequence_id)
        if sequence is not None and sequence.status == "active":
            sequence.status, sequence.updated_at = "completed", utc_now()
            session.add(sequence)
            session.commit()


def _finish(session: Session, step: FollowUpStep, status: str, error: str, due_at: Optional[datetime] = None) -> None:
    step.status, step.last_error = status, error
    if due_at is not None:
        step.due_at = due_at
    session.add(step)
    session.commit()


def _handle_failure(session: Session, step: FollowUpStep, failure: SmtpFailure, now: datetime) -> None:
    message = failure.user_message()
    logger.error(f"Seurantaviesti {step.id}: {message}")
    if failure.stage == "send":
        # Palvelin kieltäytyi selvästi -> ei lähtenyt. Muu virhe SEND-vaiheessa (katkennut yhteys) on epäselvä.
        if "refused" in failure.hint:
            _finish(session, step, "failed", message)
        else:
            _finish(session, step, "needs_review", message)
    elif step.attempts >= MAX_ATTEMPTS:
        _finish(session, step, "failed", message)
    else:
        _finish(session, step, "scheduled", message, due_at=now + RETRY_DELAY)
