from dataclasses import dataclass
from typing import Callable, Optional

import pytest

from app.utils.contact_finder import (
    ContactEmail,
    deobfuscate,
    extract_emails,
    find_contact_email,
    find_contact_links,
)


@dataclass
class _Page:
    url: str
    text: str
    status_code: int = 200


Site = dict[str, _Page]


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Callable[[Site], list[str]]:
    """Asentaa mockatun fetch_pagen. Palauttaa listan haetuista URL:eista."""

    def _install(pages: Site) -> list[str]:
        fetched: list[str] = []

        def _fetch(url: str) -> Optional[_Page]:
            fetched.append(url)
            return pages.get(url)

        monkeypatch.setattr("app.utils.contact_finder.fetch_page", _fetch)
        return fetched

    return _install


def _cf_encode(email: str, key: int = 0x42) -> str:
    return f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in email)


# --- Poiminta ---

def test_mailto_link() -> None:
    html = '<a href="mailto:Info@Parturi.fi?subject=Ajanvaraus">Lähetä viesti</a>'
    assert extract_emails(html) == [("info@parturi.fi", "mailto")]


def test_plain_text_email() -> None:
    assert extract_emails("<p>Sähköposti: myynti@parturi.fi.</p>") == [("myynti@parturi.fi", "text")]


@pytest.mark.parametrize(
    "text",
    [
        "info(at)parturi.fi",
        "info (at) parturi.fi",
        "info [at] parturi.fi",
        "info{at}parturi.fi",
        "info [ät] parturi [dot] fi",
        "info(at)parturi(piste)fi",
    ],
)
def test_obfuscated_email(text: str) -> None:
    assert extract_emails(f"<p>{text}</p>") == [("info@parturi.fi", "obfuscated")]


def test_deobfuscate_leaves_normal_text() -> None:
    assert deobfuscate("Tavataan (at) 10 klo") == "Tavataan@10 klo"  # ei EMAIL_RE-osumaa
    assert extract_emails("<p>Tavataan (at) 10 klo</p>") == []


def test_cloudflare_protected_email() -> None:
    html = (
        f'<a href="/cdn-cgi/l/email-protection#{_cf_encode("info@parturi.fi")}">'
        f'<span class="__cf_email__" data-cfemail="{_cf_encode("ajanvaraus@parturi.fi")}">[email&#160;protected]</span></a>'
    )
    assert extract_emails(html) == [("info@parturi.fi", "cloudflare"), ("ajanvaraus@parturi.fi", "cloudflare")]


@pytest.mark.parametrize(
    "junk",
    [
        "logo@2x.png",
        "hero-image@3x.webp",
        "info@example.com",
        "nimi@domain.fi",
        "etunimi.sukunimi@yritys.fi",
        "noreply@parturi.fi",
        "no-reply@parturi.fi",
        "abc123@o12345.ingest.sentry.io",
        "user@wixpress.com",
    ],
)
def test_junk_addresses_filtered(junk: str) -> None:
    assert extract_emails(f"<p>{junk}</p>") == []


def test_emails_in_scripts_ignored() -> None:
    html = "<script>var dsn='https://abc@sentry.example.org/1'; var x='info@parturi.fi';</script><p>Hei</p>"
    assert extract_emails(html) == []


# --- Yhteystietolinkit ---

def test_contact_links_same_site_max_three() -> None:
    html = """
      <a href="/palvelut">Palvelut</a>
      <a href="/yhteystiedot">Yhteystiedot</a>
      <a href="https://www.parturi.fi/ota-yhteytta/">Lomake</a>
      <a href="/en/contact">Contact</a>
      <a href="/kontakt">Kontakt</a>
      <a href="https://facebook.com/parturi/contact">Facebook</a>
      <a href="mailto:info@parturi.fi">info</a>
    """
    links = find_contact_links(html, "https://parturi.fi/")
    assert links == [
        "https://parturi.fi/yhteystiedot",
        "https://www.parturi.fi/ota-yhteytta/",
        "https://parturi.fi/en/contact",
    ]


def test_contact_link_matched_by_text_or_path() -> None:
    html = '<a href="/sivu-7">Ota yhteyttä</a><a href="/info/yhteys">Löydät meidät</a>'
    assert find_contact_links(html, "https://parturi.fi/") == ["https://parturi.fi/sivu-7", "https://parturi.fi/info/yhteys"]


# --- Koko haku ---

def test_finds_email_on_contact_page_and_reports_source(site: Callable[[Site], list[str]]) -> None:
    fetched = site({
        "http://www.parturi.fi/": _Page("https://www.parturi.fi/", '<a href="/yhteystiedot">Yhteystiedot</a><a href="/hinnasto">Hinnasto</a>'),
        "https://www.parturi.fi/yhteystiedot": _Page("https://www.parturi.fi/yhteystiedot", '<a href="mailto:info@parturi.fi">info@parturi.fi</a>'),
    })
    assert find_contact_email("http://www.parturi.fi/") == ContactEmail("info@parturi.fi", "mailto on /yhteystiedot")
    # Ei muuta crawlausta: hinnastoa ei haeta
    assert fetched == ["http://www.parturi.fi/", "https://www.parturi.fi/yhteystiedot"]


def test_fetches_at_most_home_plus_three_pages(site: Callable[[Site], list[str]]) -> None:
    links = "".join(f'<a href="/yhteystiedot-{i}">Yhteystiedot {i}</a>' for i in range(6))
    fetched = site({"https://parturi.fi/": _Page("https://parturi.fi/", links)})
    assert find_contact_email("https://parturi.fi/") is None
    assert len(fetched) == 1 + 3


def test_prefers_own_domain_over_free_mail(site: Callable[[Site], list[str]]) -> None:
    site({"https://parturi.fi/": _Page("https://parturi.fi/", "<p>parturi.salo@gmail.com</p><p>tiina@parturi.fi</p>")})
    assert find_contact_email("https://parturi.fi/") == ContactEmail("tiina@parturi.fi", "text on /")


def test_prefers_generic_address_on_own_domain(site: Callable[[Site], list[str]]) -> None:
    site({"https://parturi.fi/": _Page("https://parturi.fi/", "<p>tiina@parturi.fi</p><p>asiakaspalvelu@parturi.fi</p>")})
    result = find_contact_email("https://parturi.fi/")
    assert result is not None
    assert result.email == "asiakaspalvelu@parturi.fi"


def test_free_mail_used_when_only_option(site: Callable[[Site], list[str]]) -> None:
    site({"https://parturi.fi/": _Page("https://parturi.fi/", '<a href="mailto:parturisalo@gmail.com">Sähköposti</a>')})
    assert find_contact_email("https://parturi.fi/") == ContactEmail("parturisalo@gmail.com", "mailto on /")


def test_no_email_found_does_not_guess(site: Callable[[Site], list[str]]) -> None:
    site({"https://parturi.fi/": _Page("https://parturi.fi/", "<p>Soita 09 123 4567</p>")})
    assert find_contact_email("https://parturi.fi/") is None


@pytest.mark.parametrize("page", [None, _Page("https://parturi.fi/", "", status_code=500)])
def test_site_down_returns_none(site: Callable[[Site], list[str]], page: Optional[_Page]) -> None:
    site({"https://parturi.fi/": page} if page else {})
    assert find_contact_email("https://parturi.fi/") is None
