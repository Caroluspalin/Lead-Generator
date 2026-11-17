"""Vastausten tunnistus tallennetuilla esimerkkiviesteillä. Ei IMAP-yhteyttä: haku korvataan fake-funktiolla."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from app import replies
from app.models import FollowUpSequence, FollowUpStep, Lead, MailboxState
from tests.conftest import USER_A

MAIL = Path(__file__).parent / "fixtures" / "mail"
NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
OWN = "palin@palinweb.fi"
CFG = replies.ImapConfig(host="imap.test", user="palin@palinweb.fi", password="secret")


def raw(name: str) -> bytes:
    return (MAIL / f"{name}.eml").read_bytes()


def make_active(session: Session, email: str = "info@yritys.fi", first_id: str = "<first@palinweb.fi>") -> tuple[Lead, FollowUpSequence]:
    lead = Lead(user_id=USER_A, name="Parturi", city="Espoo", email=email, pipeline_status="Contacted")
    session.add(lead)
    session.flush()
    seq = FollowUpSequence(user_id=USER_A, lead_id=lead.id, status="active")
    session.add(seq)
    session.flush()
    base: dict[str, Any] = {"user_id": USER_A, "sequence_id": seq.id, "lead_id": lead.id, "subject": "S", "body": "b"}
    session.add_all([
        FollowUpStep(step_no=0, status="sent", sent_at=NOW - timedelta(days=3), message_id=first_id, to_email=email, **base),
        FollowUpStep(step_no=1, status="sent", sent_at=NOW - timedelta(days=1), message_id="<step1@palinweb.fi>", to_email=email, **base),
        FollowUpStep(step_no=2, status="scheduled", due_at=NOW + timedelta(days=5), **base),
    ])
    session.commit()
    return lead, seq



def steps_of(session: Session, seq: FollowUpSequence) -> dict[int, str]:
    return {s.step_no: s.status for s in session.exec(select(FollowUpStep).where(FollowUpStep.sequence_id == seq.id)).all()}


def test_reply_with_in_reply_to_stops_sequence(session: Session) -> None:
    lead, seq = make_active(session)
    out = replies.handle_message(session, raw("reply"), OWN, NOW)
    session.commit()
    session.refresh(seq)
    assert out.action == "replied" and seq.status == "replied" and seq.stop_reason == "replied" and seq.replied_at == NOW
    assert steps_of(session, seq)[2] == "stopped"
    session.refresh(lead)
    assert lead.do_not_contact is False and lead.pipeline_status == "Contacted"


def test_reply_without_threading_matches_by_sender_address(session: Session) -> None:
    _, seq = make_active(session)
    assert replies.handle_message(session, raw("reply_no_threading"), OWN, NOW).action == "replied"
    session.commit()
    session.refresh(seq)
    assert seq.status == "replied"


def test_address_match_is_case_insensitive(session: Session) -> None:
    _, seq = make_active(session, email="Info@Yritys.fi")
    assert replies.handle_message(session, raw("reply_no_threading"), OWN, NOW).action == "replied"


@pytest.mark.parametrize("name", ["auto_ooo", "auto_subject_only"])
def test_auto_replies_do_not_stop_sequence(session: Session, name: str) -> None:
    _, seq = make_active(session)
    assert replies.handle_message(session, raw(name), OWN, NOW).action == "ignored"
    session.commit()
    session.refresh(seq)
    assert seq.status == "active" and steps_of(session, seq)[2] == "scheduled"


def test_unknown_sender_is_ignored(session: Session) -> None:
    _, seq = make_active(session, email="muu@toinen.fi", first_id="<other@palinweb.fi>")
    assert replies.handle_message(session, raw("reply_no_threading"), OWN, NOW).action == "ignored"
    session.refresh(seq)
    assert seq.status == "active"


def test_own_copy_of_sent_mail_is_ignored(session: Session) -> None:
    make_active(session, email="palin@palinweb.fi")
    own_copy = raw("reply_no_threading").replace(b"info@yritys.fi", b"palin@palinweb.fi")
    assert replies.handle_message(session, own_copy, OWN, NOW).action == "ignored"


def test_unsubscribe_mailto_marks_dnc_and_stops(session: Session) -> None:
    lead, seq = make_active(session)
    out = replies.handle_message(session, raw("unsubscribe_mailto"), OWN, NOW)
    session.commit()
    session.refresh(lead)
    session.refresh(seq)
    assert out.action == "opt_out" and lead.do_not_contact is True
    assert seq.status == "stopped" and seq.stop_reason == "opt_out" and steps_of(session, seq)[2] == "stopped"


def test_ei_kiitos_reply_marks_dnc(session: Session) -> None:
    lead, _ = make_active(session)
    assert replies.handle_message(session, raw("ei_kiitos"), OWN, NOW).action == "opt_out"
    session.commit()
    session.refresh(lead)
    assert lead.do_not_contact is True


def test_unsubscribe_marks_known_lead_dnc_even_without_open_sequence(session: Session) -> None:
    lead = Lead(user_id=USER_A, name="P", city="Espoo", email="info@yritys.fi")
    session.add(lead)
    session.commit()
    replies.handle_message(session, raw("unsubscribe_mailto"), OWN, NOW)
    session.commit()
    session.refresh(lead)
    assert lead.do_not_contact is True


def test_hard_bounce_stops_sequence_but_keeps_email(session: Session) -> None:
    lead, seq = make_active(session)
    assert replies.handle_message(session, raw("bounce_hard"), OWN, NOW).action == "bounced"
    session.commit()
    session.refresh(seq)
    session.refresh(lead)
    assert seq.status == "stopped" and seq.stop_reason == "bounced" and lead.email == "info@yritys.fi"
    assert lead.do_not_contact is False


def test_soft_bounce_does_not_stop(session: Session) -> None:
    _, seq = make_active(session)
    assert replies.handle_message(session, raw("bounce_soft"), OWN, NOW).action == "ignored"
    session.refresh(seq)
    assert seq.status == "active"


def test_reply_is_idempotent(session: Session) -> None:
    _, seq = make_active(session)
    replies.handle_message(session, raw("reply"), OWN, NOW)
    session.commit()
    assert replies.handle_message(session, raw("reply"), OWN, NOW + timedelta(hours=1)).action == "ignored"
    session.refresh(seq)
    assert seq.replied_at == NOW


def test_reply_to_completed_sequence_marks_replied(session: Session) -> None:
    _, seq = make_active(session)
    seq.status = "completed"
    session.add(seq)
    session.commit()
    assert replies.handle_message(session, raw("reply"), OWN, NOW).action == "replied"


def test_check_mailbox_tracks_uid_and_handles_messages(engine: Engine, session: Session) -> None:
    _, seq = make_active(session)
    calls: list[dict[str, Any]] = []

    def fake_fetch(cfg: replies.ImapConfig, *, last_uid: int, uidvalidity: Any, now: datetime) -> replies.FetchResult:
        calls.append({"last_uid": last_uid, "uidvalidity": uidvalidity})
        msgs = [(7, raw("auto_ooo")), (8, raw("reply"))] if last_uid == 0 else []
        return replies.FetchResult(555, msgs)

    outcomes = replies.check_mailbox(engine, CFG, OWN, now=NOW, fetch=fake_fetch)
    assert [o.action for o in outcomes] == ["ignored", "replied"]
    assert replies.check_mailbox(engine, CFG, OWN, now=NOW, fetch=fake_fetch) == []
    assert calls == [{"last_uid": 0, "uidvalidity": None}, {"last_uid": 8, "uidvalidity": 555}]
    with Session(engine) as s:
        state = s.exec(select(MailboxState)).one()
        assert (state.account, state.last_uid, state.uidvalidity) == (CFG.user, 8, 555)
        row = s.get(FollowUpSequence, seq.id)
        assert row is not None and row.status == "replied"


def test_check_mailbox_resets_uid_when_uidvalidity_changes(engine: Engine, session: Session) -> None:
    session.add(MailboxState(account=CFG.user, uidvalidity=1, last_uid=50))
    session.commit()
    replies.check_mailbox(engine, CFG, OWN, now=NOW, fetch=lambda *a, **k: replies.FetchResult(2, [(3, raw("auto_ooo"))]))
    with Session(engine) as s:
        state = s.exec(select(MailboxState)).one()
        assert (state.last_uid, state.uidvalidity) == (3, 2)


def test_imap_fetch_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[tuple[str, Any]] = []

    class FakeImap:
        def __init__(self, *a: Any, **k: Any) -> None: ...
        def login(self, u: str, p: str) -> tuple[str, list[bytes]]:
            return "OK", []
        def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
            log.append(("select", readonly))
            return "OK", [b"1"]
        def response(self, name: str) -> tuple[str, list[bytes]]:
            return name, [b"42"]
        def uid(self, cmd: str, *args: Any) -> tuple[str, list[Any]]:
            log.append((cmd, args))
            if cmd == "SEARCH":
                return "OK", [b"5"]
            return "OK", [(b"5 (BODY[] {10}", b"raw-bytes"), b")"]
        def logout(self) -> None: ...

    monkeypatch.setattr("imaplib.IMAP4_SSL", FakeImap)
    res = replies.fetch_new_messages(CFG, last_uid=0, uidvalidity=None, now=NOW)
    assert res.uidvalidity == 42 and res.messages == [(5, b"raw-bytes")]
    assert ("select", True) in log
    assert any(c == "FETCH" and "PEEK" in a[1] for c, a in log if c == "FETCH")


def test_imap_loop_is_off_by_default_and_derives_host(monkeypatch: pytest.MonkeyPatch) -> None:
    import re

    from app import main

    assert main.IMAP_ENABLED is False and main._imap_config() is None
    assert re.sub(r"^smtp", "imap", "smtp.mail.me.com") == "imap.mail.me.com"
    for name, value in [("IMAP_ENABLED", True), ("IMAP_HOST", "imap.test"), ("IMAP_USER", "u"), ("IMAP_PASSWORD", "p")]:
        monkeypatch.setattr(f"app.main.{name}", value)
    assert main._imap_config() == replies.ImapConfig(host="imap.test", user="u", password="p", port=993)
