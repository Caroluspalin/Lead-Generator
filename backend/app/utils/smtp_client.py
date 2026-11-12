"""SMTP-yhteys ja virheiden luokittelu (endpoint /send-email ja scripts/smtp_check.py).

Portti 465: implisiittinen TLS (SMTP_SSL). Muut portit (587): SMTP + EHLO + STARTTLS + EHLO.
Virheet muutetaan SmtpFailureksi, jonka viesti ei koskaan sisällä salasanaa tai tunnuksia.
"""
from __future__ import annotations

import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from email.message import Message
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, getaddresses, make_msgid
from typing import Callable, Literal, Optional

import certifi

SMTP_TIMEOUT_SECONDS = 20

FailureKind = Literal["config", "connection", "tls", "auth", "send"]
Stage = Literal["connect", "ehlo", "starttls", "login", "send"]

_KIND_LABEL: dict[FailureKind, str] = {
    "config": "SMTP configuration error",
    "connection": "SMTP connection error",
    "tls": "SMTP TLS error",
    "auth": "SMTP login error",
    "send": "SMTP sending error",
}


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    from_addr: str

    def missing(self) -> list[str]:
        names = {"SMTP_HOST": self.host, "SMTP_USER": self.user, "SMTP_PASSWORD": self.password, "SMTP_FROM": self.from_addr}
        return [k for k, v in names.items() if not v]


class SmtpFailure(Exception):
    def __init__(self, kind: FailureKind, stage: Optional[Stage], hint: str, server_reply: str = "") -> None:
        self.kind = kind
        self.stage = stage
        self.hint = hint
        self.server_reply = server_reply
        super().__init__(self.user_message())

    def user_message(self) -> str:
        stage = f" during {self.stage.upper() if self.stage in ('ehlo', 'starttls') else self.stage}" if self.stage else ""
        reply = f" Server reply: {self.server_reply}" if self.server_reply else ""
        return f"{_KIND_LABEL[self.kind]}{stage}: {self.hint}{reply}"


def local_hostname() -> str:
    # macOS:n socket.getfqdn() palauttaa usein käänteis-DNS-nimen (…ip6.arpa) tai .local-nimen,
    # joita jotkin palvelimet eivät hyväksy EHLO-nimeksi. Silloin IP-literaali (RFC 5321 4.1.3).
    name = socket.getfqdn()
    if "." in name and not name.endswith((".arpa", ".local", ".localdomain")):
        return name
    return "[127.0.0.1]"


def tls_context() -> ssl.SSLContext:
    # Varmennettu TLS; macOS-venvissä ei ole järjestelmän CA-bundlea, joten certifi (kuten auth.py)
    return ssl.create_default_context(cafile=certifi.where())


def _reply_text(code: int, msg: bytes | str) -> str:
    text = msg.decode("utf-8", "replace") if isinstance(msg, bytes) else str(msg)
    return f"{code} {' '.join(text.split())}"[:200]


class _RedactingMixin:
    """Debug-tulosteesta piilotetaan AUTH-vaihe kokonaan (base64-tunnukset ja salasana).

    debuglevel luokkatasolla, jotta myös konstruktorin connect + palvelimen tervehdys näkyvät.
    Host annetaan konstruktorille: pelkkä connect() ei aseta _hostia, jolloin STARTTLS:n
    varmenteen nimitarkistus kaatuu (server_hostname tyhjä).
    """

    debuglevel = 1
    _secrets: tuple[str, ...] = ()
    _in_auth = False
    _emit: Callable[[str], None] = print

    def __init__(self, *args: object, emit: Callable[[str], None], secrets: tuple[str, ...], **kwargs: object) -> None:
        self._emit = emit
        self._secrets = secrets
        super().__init__(*args, **kwargs)  # type: ignore[call-arg]

    def _print_debug(self, *args: object) -> None:
        line = " ".join(str(a) for a in args)
        if line.startswith("send:") and ("AUTH" in line.upper() or self._in_auth):
            self._in_auth = True
            line = "send: <AUTH data redacted>"
        elif line.startswith("reply:") and self._in_auth and "retcode (334)" in line:
            line = "reply: retcode (334); <challenge redacted>"
        elif line.startswith("reply:") and self._in_auth and "retcode (" in line:
            self._in_auth = False
        for secret in self._secrets:
            if secret:
                line = line.replace(secret, "<redacted>")
        self._emit(line)


class _DebugSMTP(_RedactingMixin, smtplib.SMTP):
    pass


class _DebugSMTPSSL(_RedactingMixin, smtplib.SMTP_SSL):
    pass


def open_smtp(
    cfg: SmtpConfig,
    *,
    timeout: float = SMTP_TIMEOUT_SECONDS,
    debug: Optional[Callable[[str], None]] = None,
    on_stage: Optional[Callable[[Stage], None]] = None,
) -> smtplib.SMTP:
    """Avaa kirjautuneen yhteyden. Heittää SmtpFailure jos jokin vaihe epäonnistuu."""
    stage: Stage = "connect"

    def enter(next_stage: Stage) -> None:
        nonlocal stage
        stage = next_stage
        if on_stage:
            on_stage(next_stage)

    server: Optional[smtplib.SMTP] = None
    try:
        enter("connect")
        implicit_tls = cfg.port == 465
        local = local_hostname()
        if debug:
            secrets = (cfg.password, cfg.user, cfg.from_addr)
            if implicit_tls:
                server = _DebugSMTPSSL(cfg.host, cfg.port, local, timeout=timeout, context=tls_context(), emit=debug, secrets=secrets)
            else:
                server = _DebugSMTP(cfg.host, cfg.port, local, timeout=timeout, emit=debug, secrets=secrets)
        elif implicit_tls:
            server = smtplib.SMTP_SSL(cfg.host, cfg.port, local, timeout=timeout, context=tls_context())
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, local, timeout=timeout)

        enter("ehlo")
        server.ehlo()
        if not implicit_tls:
            enter("starttls")
            if not server.has_extn("starttls"):
                raise SmtpFailure("tls", "starttls", "the server does not offer STARTTLS on this port. Try port 465.")
            server.starttls(context=tls_context())
            enter("ehlo")
            server.ehlo()

        enter("login")
        server.login(cfg.user, cfg.password)
        return server
    except BaseException as exc:
        if server is not None:
            _close_quietly(server)
        if isinstance(exc, SmtpFailure):
            raise
        if isinstance(exc, Exception):
            raise classify(exc, stage) from None
        raise


def build_message(from_addr: str, to: str, subject: str, body: str, from_name: str = "") -> MIMEText:
    # Date ja Message-ID mukaan: ilman niitä viesti näyttää roskapostilta ja palvelin voi katkaista DATA-vaiheessa
    msg = MIMEText(body, "plain", "utf-8")
    # formataddr koodaa ääkköset (RFC 2047); Message-ID:n domain ja kirjekuori tulevat pelkästä osoitteesta
    msg["From"] = formataddr((from_name, from_addr)) if from_name else from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    domain = from_addr.rsplit("@", 1)[-1] if "@" in from_addr else None
    msg["Message-ID"] = make_msgid(domain=domain)
    return msg


def send_mail(cfg: SmtpConfig, msg: Message, *, bcc: str = "", timeout: float = SMTP_TIMEOUT_SECONDS) -> None:
    # Piilokopio vain kirjekuoreen (RCPT TO), ei Bcc-otsaketta, joten vastaanottaja ei näe sitä
    recipients = [addr for _, addr in getaddresses(msg.get_all("To", [])) if addr]
    if bcc and bcc.lower() not in (r.lower() for r in recipients):
        recipients.append(bcc)
    server = open_smtp(cfg, timeout=timeout)
    try:
        server.send_message(msg, from_addr=cfg.from_addr, to_addrs=recipients)
    except SmtpFailure:
        raise
    except Exception as exc:
        raise classify(exc, "send") from None
    finally:
        _close_quietly(server)


def _close_quietly(server: smtplib.SMTP) -> None:
    try:
        server.quit()
    except Exception:
        try:
            server.close()
        except Exception:
            pass


def classify(exc: Exception, stage: Stage) -> SmtpFailure:
    """Muuntaa poikkeuksen turvalliseksi, tyypitetyksi virheeksi (ei tunnuksia viestiin)."""
    if isinstance(exc, ssl.SSLCertVerificationError):
        return SmtpFailure("tls", stage, "the server certificate could not be verified.")
    if isinstance(exc, ssl.SSLError):
        return SmtpFailure("tls", stage, f"TLS handshake failed ({getattr(exc, 'reason', None) or type(exc).__name__}). Check SMTP_PORT (587 = STARTTLS, 465 = SSL).")
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return SmtpFailure(
            "auth", "login",
            "the server rejected the username or password. Use the full email address as SMTP_USER and an app-specific password.",
            _reply_text(exc.smtp_code, exc.smtp_error),
        )
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return SmtpFailure("tls" if stage == "starttls" else "auth", stage, "the server does not support this step on this port.")
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        hints: dict[Stage, tuple[FailureKind, str]] = {
            "connect": ("connection", "the server closed the connection before greeting. Check SMTP_HOST and SMTP_PORT."),
            "ehlo": ("connection", "the server closed the connection after the greeting."),
            "starttls": ("tls", "the server closed the connection during the TLS upgrade. Check SMTP_PORT (587 = STARTTLS, 465 = SSL)."),
            "login": ("auth", "the server closed the connection during login. This usually means the username or app-specific password is wrong."),
            "send": ("send", "the server closed the connection while sending. SMTP_FROM must be your own address or an alias of the SMTP account."),
        }
        kind, hint = hints[stage]
        return SmtpFailure(kind, stage, hint)
    if isinstance(exc, (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError)):
        code = getattr(exc, "smtp_code", None)
        reply = _reply_text(code, getattr(exc, "smtp_error", b"")) if code else ""
        if isinstance(exc, smtplib.SMTPRecipientsRefused):
            return SmtpFailure("send", "send", "the server refused the recipient address.")
        return SmtpFailure("send", "send", "the server refused the message. SMTP_FROM must match the SMTP account or one of its aliases.", reply)
    if isinstance(exc, smtplib.SMTPConnectError):
        return SmtpFailure("connection", "connect", "the server refused the connection.", _reply_text(exc.smtp_code, exc.smtp_error))
    if isinstance(exc, smtplib.SMTPResponseException):
        kind: FailureKind = "auth" if stage == "login" else "send" if stage == "send" else "connection"
        return SmtpFailure(kind, stage, "unexpected server response.", _reply_text(exc.smtp_code, exc.smtp_error))
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return SmtpFailure("connection", stage, f"timed out after {SMTP_TIMEOUT_SECONDS} s. Check SMTP_HOST, SMTP_PORT and that the network allows outgoing SMTP.")
    if isinstance(exc, socket.gaierror):
        return SmtpFailure("connection", stage, "the SMTP host name could not be resolved. Check SMTP_HOST.")
    if isinstance(exc, OSError):
        return SmtpFailure("connection", stage, f"network error ({type(exc).__name__}). Check SMTP_HOST, SMTP_PORT and the network.")
    fallback: dict[Stage, FailureKind] = {
        "connect": "connection", "ehlo": "connection", "starttls": "tls", "login": "auth", "send": "send",
    }
    return SmtpFailure(fallback[stage], stage, f"unexpected error ({type(exc).__name__}).")
