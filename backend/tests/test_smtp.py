"""SMTP: vaihejärjestys (587 STARTTLS / 465 SSL), virheiden luokittelu, ei salaisuuksia viesteissä tai debugissa."""
import smtplib
import socket
import ssl
from email.header import decode_header, make_header
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from app.utils import smtp_client
from app.utils.smtp_client import SmtpConfig, SmtpFailure, _DebugSMTP, build_message, classify, open_smtp, send_mail

PASSWORD = "abcd-efgh-ijkl-mnop"
CFG = SmtpConfig(host="smtp.mail.me.com", port=587, user="me@icloud.com", password=PASSWORD, from_addr="me@icloud.com")


class FakeSMTP:
    """Kirjaa kutsut; fail_at = vaihe, jossa heitetään annettu poikkeus."""

    instances: list["FakeSMTP"] = []
    fail_at: Optional[str] = None
    error: Exception = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    starttls_offered = True

    def __init__(self, host: str = "", port: int = 0, local_hostname: Optional[str] = None, **kwargs: Any) -> None:
        self.calls: list[str] = [f"connect {host}:{port}"]
        self.kwargs = kwargs
        self.local_hostname = local_hostname
        FakeSMTP.instances.append(self)
        self._maybe_fail("connect")

    def _maybe_fail(self, stage: str) -> None:
        if FakeSMTP.fail_at == stage:
            raise FakeSMTP.error

    def ehlo(self) -> None:
        self.calls.append("ehlo")
        self._maybe_fail("ehlo")

    def has_extn(self, name: str) -> bool:
        return name == "starttls" and FakeSMTP.starttls_offered

    def starttls(self, context: Optional[ssl.SSLContext] = None) -> None:
        assert isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_REQUIRED
        self.calls.append("starttls")
        self._maybe_fail("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append("login")
        self._maybe_fail("login")

    def send_message(self, msg: Any, from_addr: Optional[str] = None, to_addrs: Optional[list[str]] = None) -> None:
        self.calls.append("send")
        self.sent = (msg, from_addr, to_addrs)
        self._maybe_fail("send")

    def quit(self) -> None:
        self.calls.append("quit")

    def close(self) -> None:
        self.calls.append("close")


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.fail_at = None
    FakeSMTP.error = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    FakeSMTP.starttls_offered = True
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_port_587_uses_ehlo_starttls_ehlo_login_with_timeout(fake_smtp: type[FakeSMTP]) -> None:
    send_mail(CFG, build_message(CFG.from_addr, "x@y.fi", "S", "B"))
    server = fake_smtp.instances[0]
    assert server.calls == ["connect smtp.mail.me.com:587", "ehlo", "starttls", "ehlo", "login", "send", "quit"]
    assert server.kwargs["timeout"] == smtp_client.SMTP_TIMEOUT_SECONDS


def test_port_465_uses_ssl_without_starttls(fake_smtp: type[FakeSMTP]) -> None:
    cfg = SmtpConfig(host="smtp.mail.me.com", port=465, user="me@icloud.com", password=PASSWORD, from_addr="me@icloud.com")
    send_mail(cfg, build_message(cfg.from_addr, "x@y.fi", "S", "B"))
    server = fake_smtp.instances[0]
    assert server.calls == ["connect smtp.mail.me.com:465", "ehlo", "login", "send", "quit"]
    assert isinstance(server.kwargs["context"], ssl.SSLContext)


def test_ehlo_name_avoids_reverse_dns_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getfqdn", lambda: "1.0.0.0.ip6.arpa")
    assert smtp_client.local_hostname() == "[127.0.0.1]"
    monkeypatch.setattr(socket, "getfqdn", lambda: "MacBook.local")
    assert smtp_client.local_hostname() == "[127.0.0.1]"
    monkeypatch.setattr(socket, "getfqdn", lambda: "mail.example.com")
    assert smtp_client.local_hostname() == "mail.example.com"


@pytest.mark.parametrize(
    ("stage", "error", "kind"),
    [
        ("connect", socket.gaierror("nodename"), "connection"),
        ("connect", TimeoutError(), "connection"),
        ("starttls", ssl.SSLError(1, "WRONG_VERSION_NUMBER"), "tls"),
        ("starttls", smtplib.SMTPServerDisconnected("closed"), "tls"),
        ("login", smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication failed"), "auth"),
        ("login", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "auth"),
        ("send", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "send"),
        ("send", smtplib.SMTPSenderRefused(550, b"5.7.0 From address is not one of your addresses", "x"), "send"),
    ],
)
def test_failures_are_classified_by_stage(
    fake_smtp: type[FakeSMTP], stage: str, error: Exception, kind: str
) -> None:
    fake_smtp.fail_at, fake_smtp.error = stage, error
    with pytest.raises(SmtpFailure) as info:
        send_mail(CFG, build_message(CFG.from_addr, "x@y.fi", "S", "B"))
    assert info.value.kind == kind
    assert info.value.stage == stage
    assert PASSWORD not in info.value.user_message()


def test_missing_starttls_is_tls_error(fake_smtp: type[FakeSMTP]) -> None:
    fake_smtp.starttls_offered = False
    with pytest.raises(SmtpFailure) as info:
        open_smtp(CFG)
    assert info.value.kind == "tls"
    assert "465" in info.value.user_message()


def test_unknown_error_kind_follows_stage() -> None:
    assert classify(ValueError("x"), "starttls").kind == "tls"
    assert classify(ValueError("x"), "login").kind == "auth"


def test_message_has_date_and_message_id() -> None:
    msg = build_message("me@icloud.com", "x@y.fi", "Aihe", "Hei")
    assert msg["Date"] and msg["Message-ID"].endswith("@icloud.com>")
    assert msg.get_content_charset() == "utf-8"


def test_from_header_without_name_is_plain_address() -> None:
    assert build_message("me@icloud.com", "x@y.fi", "Aihe", "Hei")["From"] == "me@icloud.com"


def test_from_header_with_name() -> None:
    msg = build_message("me@icloud.com", "x@y.fi", "Aihe", "Hei", from_name="Carolus Palin")
    assert msg["From"] == "Carolus Palin <me@icloud.com>"
    assert msg["Message-ID"].endswith("@icloud.com>")


def test_from_name_with_umlauts_is_encoded() -> None:
    msg = build_message("me@icloud.com", "x@y.fi", "Aihe", "Hei", from_name="Äijä Öhman")
    raw = msg["From"]
    assert raw.isascii() and "=?utf-8?" in raw and raw.endswith(" <me@icloud.com>")
    assert str(make_header(decode_header(raw))) == "Äijä Öhman <me@icloud.com>"
    assert msg["Message-ID"].endswith("@icloud.com>")


def test_envelope_uses_bare_address_and_bcc_stays_hidden(fake_smtp: type[FakeSMTP]) -> None:
    msg = build_message(CFG.from_addr, "x@y.fi", "S", "B", from_name="Carolus Palin")
    send_mail(CFG, msg, bcc="copy@palin.fi")
    sent, from_addr, to_addrs = fake_smtp.instances[0].sent
    assert from_addr == CFG.from_addr
    assert to_addrs == ["x@y.fi", "copy@palin.fi"]
    assert sent["Bcc"] is None and "copy@palin.fi" not in sent.as_string()


def test_no_bcc_sends_only_to_recipient(fake_smtp: type[FakeSMTP]) -> None:
    send_mail(CFG, build_message(CFG.from_addr, "x@y.fi", "S", "B"))
    assert fake_smtp.instances[0].sent[2] == ["x@y.fi"]


def test_config_repr_hides_password() -> None:
    assert PASSWORD not in repr(CFG)


def test_debug_output_redacts_auth_exchange() -> None:
    lines: list[str] = []
    server = _DebugSMTP(emit=lines.append, secrets=(PASSWORD, CFG.user, CFG.from_addr))
    server._print_debug("send:", repr("AUTH PLAIN AG1lQGljbG91ZC5jb20AYWJjZA==\r\n"))
    server._print_debug("reply:", "retcode (334); Msg: b'VXNlcm5hbWU6'")
    server._print_debug("send:", repr("bWVAaWNsb3VkLmNvbQ==\r\n"))
    server._print_debug("reply:", "retcode (235); Msg: b'2.7.0 Authentication successful'")
    server._print_debug("send:", repr(f"mail FROM:<{CFG.from_addr}>\r\n"))
    out = "\n".join(lines)
    assert "AG1lQGljbG91ZC5jb20" not in out and "bWVAaWNsb3VkLmNvbQ" not in out
    assert CFG.from_addr not in out and PASSWORD not in out
    assert "Authentication successful" in out


def test_endpoint_returns_classified_502_without_secrets(
    client_a: TestClient, fake_smtp: type[FakeSMTP], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in [("SMTP_HOST", CFG.host), ("SMTP_USER", CFG.user), ("SMTP_PASSWORD", PASSWORD), ("SMTP_FROM", CFG.from_addr)]:
        monkeypatch.setattr(f"app.main.{name}", value)
    fake_smtp.fail_at = "login"
    fake_smtp.error = smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication failed")
    res = client_a.post("/send-email", json={"to": "x@y.fi", "subject": "S", "body": "B"})
    assert res.status_code == 502
    detail = res.json()["detail"]
    assert detail.startswith("SMTP login error")
    assert "535" in detail and PASSWORD not in detail


def test_endpoint_sends_with_fixed_flow(
    client_a: TestClient, fake_smtp: type[FakeSMTP], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in [("SMTP_HOST", CFG.host), ("SMTP_USER", CFG.user), ("SMTP_PASSWORD", PASSWORD), ("SMTP_FROM", CFG.from_addr)]:
        monkeypatch.setattr(f"app.main.{name}", value)
    res = client_a.post("/send-email", json={"to": "x@y.fi", "subject": "S", "body": "B"})
    assert res.status_code == 200
    assert fake_smtp.instances[0].calls[-2:] == ["send", "quit"]
    sent, _, to_addrs = fake_smtp.instances[0].sent
    assert sent["From"] == CFG.from_addr and to_addrs == ["x@y.fi"]


def test_endpoint_uses_from_name_and_bcc(
    client_a: TestClient, fake_smtp: type[FakeSMTP], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in [
        ("SMTP_HOST", CFG.host), ("SMTP_USER", CFG.user), ("SMTP_PASSWORD", PASSWORD), ("SMTP_FROM", CFG.from_addr),
        ("SMTP_FROM_NAME", "Carolus Palin"), ("SMTP_BCC", "copy@palin.fi"),
    ]:
        monkeypatch.setattr(f"app.main.{name}", value)
    res = client_a.post("/send-email", json={"to": "x@y.fi", "subject": "S", "body": "B"})
    assert res.status_code == 200
    sent, from_addr, to_addrs = fake_smtp.instances[0].sent
    assert sent["From"] == "Carolus Palin <me@icloud.com>" and from_addr == CFG.from_addr
    assert to_addrs == ["x@y.fi", "copy@palin.fi"]
    assert sent["Bcc"] is None and "copy@palin.fi" not in sent.as_string()
