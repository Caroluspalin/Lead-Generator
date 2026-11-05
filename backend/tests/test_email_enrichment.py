from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from app.utils.contact_finder import ContactEmail


class _FakeFinder:
    def __init__(self, result: Optional[ContactEmail]) -> None:
        self.result = result
        self.calls: list[str] = []

    def __call__(self, website: str) -> Optional[ContactEmail]:
        self.calls.append(website)
        return self.result


@pytest.fixture
def finder(monkeypatch: pytest.MonkeyPatch) -> _FakeFinder:
    fake = _FakeFinder(ContactEmail("info@carmen.fi", "mailto on /yhteystiedot"))
    monkeypatch.setattr("app.main.find_contact_email", fake)
    return fake


@pytest.mark.parametrize("status", ["WEBSITE OK", "NOT MOBILE", "INSECURE"])
def test_create_lead_finds_email_in_background(
    client_a: TestClient, make_lead: Any, finder: _FakeFinder, status: str
) -> None:
    lead = make_lead(website="http://www.carmen.fi/", website_status=status)
    # TestClient ajaa background taskit ennen kuin pyyntö palaa
    assert finder.calls == ["http://www.carmen.fi/"]
    saved = client_a.get("/leads").json()[0]
    assert saved["id"] == lead["id"]
    assert saved["email"] == "info@carmen.fi"
    assert saved["email_source"] == "mailto on /yhteystiedot"
    assert saved["do_not_contact"] is False


@pytest.mark.parametrize("status", ["NO WEBSITE", "BROKEN WEBSITE", "UNKNOWN"])
def test_create_lead_skips_email_search_for_unusable_site(
    client_a: TestClient, make_lead: Any, finder: _FakeFinder, status: str
) -> None:
    make_lead(website="http://www.carmen.fi/", website_status=status)
    assert finder.calls == []
    assert client_a.get("/leads").json()[0]["email"] is None


def test_background_failure_does_not_break_create(
    client_a: TestClient, make_lead: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_url: str) -> None:
        raise RuntimeError("verkko kaatui")

    monkeypatch.setattr("app.main.find_contact_email", _boom)
    make_lead(website="http://www.carmen.fi/", website_status="WEBSITE OK")
    assert client_a.get("/leads").json()[0]["email"] is None


def test_find_email_endpoint(client_a: TestClient, make_lead: Any, finder: _FakeFinder) -> None:
    finder.result = None
    lead = make_lead(website="http://www.carmen.fi/", website_status="INSECURE")
    finder.result = ContactEmail("ajanvaraus@carmen.fi", "obfuscated on /")

    res = client_a.post(f"/leads/{lead['id']}/find-email")
    assert res.status_code == 200
    assert res.json()["email"] == "ajanvaraus@carmen.fi"
    assert res.json()["email_source"] == "obfuscated on /"


def test_find_email_not_found_keeps_lead(client_a: TestClient, make_lead: Any, finder: _FakeFinder) -> None:
    finder.result = None
    lead = make_lead(website="http://www.carmen.fi/", website_status="WEBSITE OK")
    res = client_a.post(f"/leads/{lead['id']}/find-email")
    assert res.status_code == 200
    assert res.json()["email"] is None


def test_find_email_rejects_unusable_site(client_a: TestClient, make_lead: Any, finder: _FakeFinder) -> None:
    lead = make_lead(website_status="NO WEBSITE")
    assert client_a.post(f"/leads/{lead['id']}/find-email").status_code == 422
    assert finder.calls == []


def test_find_email_other_users_lead_is_404(
    client_b: TestClient, make_lead: Any, finder: _FakeFinder
) -> None:
    lead = make_lead(website="http://www.carmen.fi/", website_status="WEBSITE OK")
    finder.calls.clear()
    assert client_b.post(f"/leads/{lead['id']}/find-email").status_code == 404
    assert finder.calls == []


def test_patch_email_and_do_not_contact(client_a: TestClient, make_lead: Any) -> None:
    lead = make_lead()
    res = client_a.patch(f"/leads/{lead['id']}", json={"email": "omistaja@carmen.fi", "do_not_contact": True})
    assert res.status_code == 200
    assert res.json()["email"] == "omistaja@carmen.fi"
    assert res.json()["do_not_contact"] is True
