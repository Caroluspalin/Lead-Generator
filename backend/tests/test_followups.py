"""Seurantaviestit: aikataulu, lähetysikkuna, päiväraja, DNC, idempotenssi ja API. SMTP aina mockattu."""
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from app import followups
from app.followups import FollowUpSettings, SenderDeps
from app.main import OPT_OUT_LINE
from app.models import FollowUpSequence, FollowUpStep, Lead
from app.utils.smtp_client import SmtpConfig, SmtpFailure
from tests.conftest import USER_A, USER_B, FakeOpenAI

UTC = timezone.utc
CFG = SmtpConfig(host="smtp.test", port=587, user="u", password="p", from_addr="palin@palinweb.fi")
SETTINGS = FollowUpSettings(send_enabled=True, daily_limit=20, min_delay_seconds=90, late_grace_days=2)
FIRST_SENT = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)  # perjantai
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)  # maanantai klo 12 Suomen aikaa


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[Message] = []
        self.error: Optional[Exception] = None

    def __call__(self, cfg: SmtpConfig, msg: Message, *, bcc: str = "") -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(msg)


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


def deps(sender: FakeSender, demo_ok: bool = True) -> SenderDeps:
    return SenderDeps(smtp=CFG, from_name="Carolus Palin", send=sender, demo_ok=lambda _s, _l, _u: demo_ok)


def make_series(
    session: Session,
    *,
    user_id: str = USER_A,
    status: str = "active",
    email: str = "info@yritys.fi",
    dnc: bool = False,
    demo_url: Optional[str] = None,
) -> tuple[Lead, FollowUpSequence, list[FollowUpStep]]:
    lead = Lead(user_id=user_id, name="Parturi", city="Espoo", email=email, do_not_contact=dnc, pipeline_status="Contacted")
    session.add(lead)
    session.flush()
    seq = FollowUpSequence(user_id=user_id, lead_id=lead.id, status=status)
    session.add(seq)
    session.flush()
    steps = [
        FollowUpStep(user_id=user_id, sequence_id=seq.id, lead_id=lead.id, step_no=0, subject="Kysymys nettisivuista",
                     body="eka", to_email=email, status="sent", sent_at=FIRST_SENT, due_at=FIRST_SENT, message_id="<first@palinweb.fi>"),
        FollowUpStep(user_id=user_id, sequence_id=seq.id, lead_id=lead.id, step_no=1, subject="Re: x",
                     body=f"Hei,\n\nMuistutus\n\n{OPT_OUT_LINE}", due_at=followups.step_due_at(FIRST_SENT, 1), demo_url=demo_url),
        FollowUpStep(user_id=user_id, sequence_id=seq.id, lead_id=lead.id, step_no=2, subject="Re: x",
                     body=f"Hei,\n\nViimeinen\n\n{OPT_OUT_LINE}", due_at=followups.step_due_at(FIRST_SENT, 2)),
    ]
    session.add_all(steps)
    session.commit()
    return lead, seq, steps


def step_status(engine: Engine, step_id: Optional[int]) -> str:
    with Session(engine) as s:
        row = s.get(FollowUpStep, step_id)
        assert row is not None
        return row.status


# --- Aikataulu ---

def test_finnish_holidays_2026() -> None:
    h = followups.finnish_holidays(2026)
    assert date(2026, 4, 3) in h and date(2026, 4, 6) in h  # pitkäperjantai, 2. pääsiäispäivä
    assert date(2026, 6, 19) in h  # juhannusaatto
    assert date(2026, 5, 14) in h  # helatorstai
    assert date(2026, 12, 24) in h


@pytest.mark.parametrize(
    ("utc_time", "expected"),
    [
        (datetime(2026, 11, 16, 6, 59, tzinfo=UTC), False),  # 8:59 Suomen aikaa
        (datetime(2026, 11, 16, 7, 0, tzinfo=UTC), True),  # 9:00
        (datetime(2026, 11, 16, 13, 59, tzinfo=UTC), True),  # 15:59
        (datetime(2026, 11, 16, 14, 0, tzinfo=UTC), False),  # 16:00
        (datetime(2026, 11, 14, 10, 0, tzinfo=UTC), False),  # lauantai
        (datetime(2026, 12, 24, 10, 0, tzinfo=UTC), False),  # jouluaatto
        (datetime(2026, 7, 1, 6, 0, tzinfo=UTC), True),  # kesäaika: 9:00 = 6:00 UTC
        (datetime(2026, 7, 1, 5, 59, tzinfo=UTC), False),
    ],
)
def test_send_window(utc_time: datetime, expected: bool) -> None:
    assert followups.in_send_window(utc_time) is expected


def test_step_due_dates_skip_weekends() -> None:
    # Perjantai 13.11. + 3 pv = maanantai 16.11.; + 8 pv = lauantai 21.11. -> maanantai 23.11. (klo 9, UTC 7)
    assert followups.step_due_at(FIRST_SENT, 1) == datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
    assert followups.step_due_at(FIRST_SENT, 2) == datetime(2026, 11, 23, 7, 0, tzinfo=UTC)


def test_rescheduled_due_is_tomorrow_at_earliest_and_two_days_after_previous() -> None:
    prev = datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
    # Perjantaina 20.11. myöhästynyt -> ei lauantaille eikä pyhälle vaan maanantaille
    assert followups.rescheduled_due_at(datetime(2026, 11, 20, 10, 0, tzinfo=UTC), prev) == datetime(2026, 11, 23, 7, 0, tzinfo=UTC)
    # Edellinen lähti eilen: 2 pv väli -> ylihuomenna
    assert followups.rescheduled_due_at(datetime(2026, 11, 17, 10, 0, tzinfo=UTC), datetime(2026, 11, 16, 8, 0, tzinfo=UTC)) == datetime(2026, 11, 18, 7, 0, tzinfo=UTC)


# --- Lähettäjä ---

def test_sends_due_step_with_headers_and_reply_subject(engine: Engine, session: Session, sender: FakeSender) -> None:
    _, _, steps = make_series(session)
    assert followups.run_once(engine, NOW, SETTINGS, deps(sender)) == steps[1].id
    assert len(sender.sent) == 1
    msg = sender.sent[0]
    assert msg["To"] == "info@yritys.fi"
    assert msg["Subject"] == "Re: Kysymys nettisivuista"
    assert msg["List-Unsubscribe"] == "<mailto:palin@palinweb.fi?subject=unsubscribe>"
    assert msg["In-Reply-To"] == "<first@palinweb.fi>"
    assert "<first@palinweb.fi>" in msg["References"]
    assert OPT_OUT_LINE in msg.get_payload(decode=True).decode()
    with Session(engine) as s:
        row = s.get(FollowUpStep, steps[1].id)
        assert row is not None and row.status == "sent" and row.sent_at == NOW and row.message_id == msg["Message-ID"]


def test_draft_sequence_sends_nothing(engine: Engine, session: Session, sender: FakeSender) -> None:
    make_series(session, status="draft")
    assert followups.run_once(engine, NOW, SETTINGS, deps(sender)) is None
    assert sender.sent == []


def test_sending_disabled_by_default(engine: Engine, session: Session, sender: FakeSender) -> None:
    make_series(session)
    assert FollowUpSettings().send_enabled is False
    assert followups.run_once(engine, NOW, FollowUpSettings(), deps(sender)) is None
    assert sender.sent == []


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 11, 14, 10, 0, tzinfo=UTC),  # lauantai
        datetime(2026, 11, 16, 14, 30, tzinfo=UTC),  # 16:30
        datetime(2026, 11, 16, 5, 0, tzinfo=UTC),  # 7:00
    ],
)
def test_outside_window_sends_nothing(engine: Engine, session: Session, sender: FakeSender, now: datetime) -> None:
    make_series(session)
    assert followups.run_once(engine, now, SETTINGS, deps(sender)) is None
    assert sender.sent == []


def test_daily_limit_counts_sent_today_and_resets_next_day(engine: Engine, session: Session, sender: FakeSender) -> None:
    make_series(session, email="a@x.fi")
    make_series(session, email="b@x.fi")
    limit = FollowUpSettings(send_enabled=True, daily_limit=1, min_delay_seconds=0)
    assert followups.run_once(engine, NOW, limit, deps(sender)) is not None
    assert followups.run_once(engine, NOW + timedelta(minutes=5), limit, deps(sender)) is None
    assert len(sender.sent) == 1
    # Seuraavana arkipäivänä toinen lähtee (due 16.11. on myöhästynyt alle 2 pv)
    assert followups.run_once(engine, NOW + timedelta(days=1), limit, deps(sender)) is not None


def test_min_delay_between_messages(engine: Engine, session: Session, sender: FakeSender) -> None:
    make_series(session, email="a@x.fi")
    make_series(session, email="b@x.fi")
    assert followups.run_once(engine, NOW, SETTINGS, deps(sender)) is not None
    assert followups.run_once(engine, NOW + timedelta(seconds=30), SETTINGS, deps(sender)) is None
    assert followups.run_once(engine, NOW + timedelta(seconds=100), SETTINGS, deps(sender)) is not None


def test_do_not_contact_stops_sequence_and_sends_nothing(engine: Engine, session: Session, sender: FakeSender) -> None:
    lead, seq, steps = make_series(session, dnc=True)
    assert followups.run_once(engine, NOW, SETTINGS, deps(sender)) is None
    assert sender.sent == []
    with Session(engine) as s:
        row = s.get(FollowUpSequence, seq.id)
        assert row is not None and row.status == "stopped" and row.stop_reason == "dnc"
    assert step_status(engine, steps[1].id) == "stopped"


def test_dnc_recipient_address_on_other_lead_blocks(engine: Engine, session: Session, sender: FakeSender) -> None:
    make_series(session, dnc=True, email="same@x.fi")
    make_series(session, email="SAME@x.fi")
    assert followups.run_once(engine, NOW, SETTINGS, deps(sender)) is None
    assert sender.sent == []


def test_same_step_cannot_be_claimed_twice(engine: Engine, session: Session) -> None:
    _, _, steps = make_series(session)
    with Session(engine) as a, Session(engine) as b:
        step_a, step_b = a.get(FollowUpStep, steps[1].id), b.get(FollowUpStep, steps[1].id)
        assert step_a is not None and step_b is not None
        assert followups._claim(a, step_a, "<m1@x>", NOW) is True
        assert followups._claim(b, step_b, "<m2@x>", NOW) is False
    assert step_status(engine, steps[1].id) == "sending"


def test_repeated_runs_send_each_step_once(engine: Engine, session: Session, sender: FakeSender) -> None:
    make_series(session)
    for minutes in range(0, 60, 2):
        followups.run_once(engine, NOW + timedelta(minutes=minutes), SETTINGS, deps(sender))
    assert len(sender.sent) == 1  # askel 2 erääntyy vasta 23.11.


def test_stale_sending_goes_to_review_and_is_not_resent(engine: Engine, session: Session, sender: FakeSender) -> None:
    _, _, steps = make_series(session)
    steps[1].status, steps[1].claimed_at = "sending", NOW - timedelta(minutes=30)
    session.add(steps[1])
    session.commit()
    assert followups.run_once(engine, NOW, SETTINGS, deps(sender)) is None
    assert sender.sent == []
    assert step_status(engine, steps[1].id) == "needs_review"


def test_fresh_sending_blocks_other_sends(engine: Engine, session: Session, sender: FakeSender) -> None:
    _, _, steps = make_series(session)
    steps[1].status, steps[1].claimed_at = "sending", NOW - timedelta(minutes=1)
    session.add(steps[1])
    session.commit()
    make_series(session, email="b@x.fi")
    assert followups.run_once(engine, NOW, SETTINGS, deps(sender)) is None
    assert step_status(engine, steps[1].id) == "sending"


def test_failure_before_send_retries_later_then_fails(engine: Engine, session: Session, sender: FakeSender) -> None:
    _, _, steps = make_series(session)
    sender.error = SmtpFailure("connection", "connect", "the server closed the connection before greeting.")
    t = NOW
    for attempt in range(1, 4):
        assert followups.run_once(engine, t, SETTINGS, deps(sender)) == steps[1].id
        expected = "scheduled" if attempt < 3 else "failed"
        assert step_status(engine, steps[1].id) == expected
        t += timedelta(minutes=20)


def test_send_stage_failures(engine: Engine, session: Session, sender: FakeSender) -> None:
    _, _, steps = make_series(session)
    _, _, steps_b = make_series(session, email="b@x.fi")
    sender.error = SmtpFailure("send", "send", "the server refused the recipient address.")
    followups.run_once(engine, NOW, SETTINGS, deps(sender))
    sender.error = SmtpFailure("send", "send", "the server closed the connection while sending.")
    followups.run_once(engine, NOW + timedelta(minutes=5), SETTINGS, deps(sender))
    assert {step_status(engine, steps[1].id), step_status(engine, steps_b[1].id)} == {"failed", "needs_review"}


def test_late_step_is_rescheduled_not_sent(engine: Engine, session: Session, sender: FakeSender) -> None:
    _, _, steps = make_series(session)
    late = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)  # 4 pv myöhässä
    assert followups.run_once(engine, late, SETTINGS, deps(sender)) is None
    assert sender.sent == []
    with Session(engine) as s:
        row = s.get(FollowUpStep, steps[1].id)
        assert row is not None and row.status == "scheduled"
        assert row.due_at == datetime(2026, 11, 23, 7, 0, tzinfo=UTC)


def test_step_two_waits_for_step_one(engine: Engine, session: Session, sender: FakeSender) -> None:
    _, _, steps = make_series(session)
    steps[1].status = "stopped"
    session.add(steps[1])
    session.commit()
    assert followups.run_once(engine, datetime(2026, 11, 23, 10, 0, tzinfo=UTC), SETTINGS, deps(sender)) is None


def test_missing_demo_blocks_step(engine: Engine, session: Session, sender: FakeSender) -> None:
    _, _, steps = make_series(session, demo_url="https://demo.test/x")
    assert followups.run_once(engine, NOW, SETTINGS, deps(sender, demo_ok=False)) is None
    assert sender.sent == []
    assert step_status(engine, steps[1].id) == "needs_review"


def test_final_step_completes_sequence(engine: Engine, session: Session, sender: FakeSender) -> None:
    _, seq, steps = make_series(session)
    steps[1].status, steps[1].sent_at = "sent", NOW
    session.add(steps[1])
    session.commit()
    assert followups.run_once(engine, datetime(2026, 11, 23, 10, 0, tzinfo=UTC), SETTINGS, deps(sender)) == steps[2].id
    with Session(engine) as s:
        row = s.get(FollowUpSequence, seq.id)
        assert row is not None and row.status == "completed"


def test_other_users_do_not_mix(engine: Engine, session: Session, sender: FakeSender) -> None:
    make_series(session, user_id=USER_B)
    assert followups.run_once(engine, NOW, FollowUpSettings(send_enabled=True, daily_limit=0, min_delay_seconds=0), deps(sender)) is None
    assert followups.sent_today(session, USER_A, NOW) == 0


# --- Tilasiirtymät ---

def test_record_initial_send_marks_contacted_and_schedules_on_approve(session: Session) -> None:
    lead = Lead(user_id=USER_A, name="P", city="Espoo", email="a@x.fi")
    session.add(lead)
    session.commit()
    seq = followups.record_initial_send(session, lead, to="a@x.fi", subject="S", body="b", message_id="<1@x>", now=FIRST_SENT)
    session.add(FollowUpStep(user_id=USER_A, sequence_id=seq.id, lead_id=lead.id, step_no=1, subject="Re: S", body="x"))
    session.commit()
    assert lead.pipeline_status == "Contacted"
    followups.approve_sequence(session, seq, NOW)
    session.commit()
    step = session.exec(select(FollowUpStep).where(FollowUpStep.step_no == 1)).one()
    assert seq.status == "active" and step.due_at == datetime(2026, 11, 16, 7, 0, tzinfo=UTC)


def test_resending_first_email_stops_old_sequence(session: Session) -> None:
    lead, seq, steps = make_series(session)
    followups.record_initial_send(session, lead, to="info@yritys.fi", subject="Uusi", body="b", message_id="<2@x>", now=NOW)
    session.commit()
    session.refresh(seq)
    session.refresh(steps[1])
    assert seq.status == "stopped" and seq.stop_reason == "resent" and steps[1].status == "stopped"


def test_initial_send_does_not_move_later_stages(session: Session) -> None:
    lead = Lead(user_id=USER_A, name="P", city="Espoo", pipeline_status="Proposal Received")
    session.add(lead)
    session.commit()
    followups.record_initial_send(session, lead, to="a@x.fi", subject="S", body="b", message_id="<1@x>", now=NOW)
    assert lead.pipeline_status == "Proposal Received"


# --- API ---

def _sequence_setup(client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]) -> int:
    fake_openai.reply = "Lähetin teille aiemmin viestin nettisivuista. Voin muokata luonnosta toiveidenne mukaan."
    return int(make_lead(email="info@yritys.fi")["id"])


def test_generate_edit_approve_flow(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead_id = _sequence_setup(client_a, make_lead, fake_openai, sender_profile)
    res = client_a.post(f"/leads/{lead_id}/followups/generate")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "draft" and [s["step_no"] for s in data["steps"]] == [1, 2]
    assert all(OPT_OUT_LINE in s["body"] and s["due_at"] is None for s in data["steps"])
    assert "viimeinen viestini" in data["steps"][1]["body"]
    assert "390" not in data["steps"][0]["body"]
    step_id = data["steps"][0]["id"]

    edited = client_a.patch(f"/followups/steps/{step_id}", json={"body": "Hei,\n\nOma teksti"})
    assert edited.status_code == 200 and OPT_OUT_LINE in edited.json()["body"]

    approved = client_a.post(f"/leads/{lead_id}/followups/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "active"
    # Askel 0 puuttuu: aikoja ei vielä ole, joten mikään ei voi lähteä
    assert all(s["due_at"] is None for s in approved.json()["steps"])
    assert client_a.post(f"/leads/{lead_id}/followups/generate").status_code == 409


def test_send_email_records_first_message_and_schedules_approved_steps(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lead_id = _sequence_setup(client_a, make_lead, fake_openai, sender_profile)
    client_a.post(f"/leads/{lead_id}/followups/generate")
    client_a.post(f"/leads/{lead_id}/followups/approve")
    sent: list[Message] = []
    for name, value in [("SMTP_HOST", "h"), ("SMTP_USER", "u"), ("SMTP_PASSWORD", "p"), ("SMTP_FROM", "palin@palinweb.fi")]:
        monkeypatch.setattr(f"app.main.{name}", value)
    monkeypatch.setattr("app.main.send_mail", lambda cfg, msg, bcc="": sent.append(msg))
    res = client_a.post("/send-email", json={"to": "info@yritys.fi", "subject": "Kysymys", "body": "Hei", "lead_id": lead_id})
    assert res.status_code == 200
    assert sent[0]["List-Unsubscribe"].startswith("<mailto:palin@palinweb.fi")
    data = client_a.get(f"/leads/{lead_id}/followups").json()
    assert all(s["due_at"] is not None and s["status"] == "scheduled" for s in data["steps"])
    assert data["steps"][0]["subject"] == "Re: Kysymys"  # seuraa lähetetyn aloitusviestin aihetta
    lead = next(item for item in client_a.get("/leads").json() if item["id"] == lead_id)
    assert lead["pipeline_status"] == "Contacted" and lead["followup_status"] == "active" and lead["followup_next_at"]


def test_marking_lead_dnc_stops_sequence(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead_id = _sequence_setup(client_a, make_lead, fake_openai, sender_profile)
    client_a.post(f"/leads/{lead_id}/followups/generate")
    client_a.post(f"/leads/{lead_id}/followups/approve")
    assert client_a.patch(f"/leads/{lead_id}", json={"do_not_contact": True}).status_code == 200
    data = client_a.get(f"/leads/{lead_id}/followups").json()
    assert data["status"] == "stopped" and data["stop_reason"] == "dnc"
    assert all(s["status"] == "stopped" for s in data["steps"])


def test_manual_stop_and_dnc_lead_cannot_generate(
    client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead_id = _sequence_setup(client_a, make_lead, fake_openai, sender_profile)
    client_a.post(f"/leads/{lead_id}/followups/generate")
    stopped = client_a.post(f"/leads/{lead_id}/followups/stop")
    assert stopped.json()["status"] == "stopped" and stopped.json()["stop_reason"] == "manual"
    client_a.patch(f"/leads/{lead_id}", json={"do_not_contact": True})
    assert client_a.post(f"/leads/{lead_id}/followups/generate").status_code == 409


def test_followups_are_tenant_isolated(
    client_a: TestClient, client_b: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]
) -> None:
    lead_id = _sequence_setup(client_a, make_lead, fake_openai, sender_profile)
    data = client_a.post(f"/leads/{lead_id}/followups/generate").json()
    assert client_b.get(f"/leads/{lead_id}/followups").status_code == 404
    assert client_b.post(f"/leads/{lead_id}/followups/approve").status_code == 404
    assert client_b.post(f"/leads/{lead_id}/followups/stop").status_code == 404
    assert client_b.patch(f"/followups/steps/{data['steps'][0]['id']}", json={"body": "x"}).status_code == 404


def test_prompt_has_no_price_and_questions_forbidden() -> None:
    from app.main import FOLLOWUP_SYSTEM_PROMPT

    assert "EI kysymyksiä" in FOLLOWUP_SYSTEM_PROMPT and "hintaa" in FOLLOWUP_SYSTEM_PROMPT


def test_followup_body_keeps_draft_reference_drops_questions_and_links() -> None:
    from app.main import build_followup_body
    from app.models import SenderProfile

    profile = SenderProfile(user_id=USER_A, name="Palin", short_intro="x")
    body = build_followup_body(
        "Hei,\n\nLähetin teille aiemmin viestin ja luonnoksen nettisivuista. Katso https://x.fi Kiinnostaisiko?",
        profile, 1, "https://demo.test/a",
    )
    assert "Lähetin teille aiemmin viestin ja luonnoksen nettisivuista." in body
    assert "?" not in body and "https://x.fi" not in body
    assert body.count("https://demo.test/a") == 1 and body.endswith(OPT_OUT_LINE)
    assert "viimeinen viestini" not in body
    assert "viimeinen viestini" in build_followup_body("Hyvä.", profile, 2, None)
