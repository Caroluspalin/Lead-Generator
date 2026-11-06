"""Demojen julkaisu R2:een (fake store), poisto, vanheneminen ja sähköpostilinkki."""
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.demo_publish import R2Config, load_r2_config, object_key
from app.main import run_demo_expiry
from app.models import Demo
from tests.conftest import FakeOpenAI
from tests.test_demo_site import VALID

PUBLIC_BASE = "https://agency-hunter-demos.palin.workers.dev"
CONFIG = R2Config(
    account_id="acc", access_key_id="id", secret_access_key="secret", bucket="agency-hunter-demos",
    public_base_url=PUBLIC_BASE,
)


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, Optional[datetime]]] = {}
        self.deleted: list[str] = []
        self.fail_put = False
        self.fail_delete = False

    def put(self, key: str, body: bytes, *, expires_at: Optional[datetime]) -> None:
        if self.fail_put:
            raise RuntimeError("R2 down")
        self.objects[key] = (body, expires_at)

    def delete(self, key: str) -> None:
        if self.fail_delete:
            raise RuntimeError("R2 down")
        self.deleted.append(key)
        self.objects.pop(key, None)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: fake)
    return fake


@pytest.fixture
def demo(client_a: TestClient, make_lead: Any, fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]) -> dict[str, Any]:
    fake_openai.reply = json.dumps(VALID)
    lead = make_lead(name="Parturi-Kampaamo Taina Lantiainen", city="Kauniainen", phone="050 5936073",
                     website_status="NO WEBSITE", primary_type="hair_salon")
    created = client_a.post(f"/leads/{lead['id']}/demo", json={}).json()
    return {**created, "lead": lead}


def _publish(client: TestClient, demo: dict[str, Any]) -> dict[str, Any]:
    res = client.post(f"/leads/{demo['lead_id']}/demo/publish")
    assert res.status_code == 200, res.text
    return res.json()


# --- Konfiguraatio ---

def test_config_requires_all_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "DEMO_PUBLIC_BASE_URL"):
        monkeypatch.setenv(key, "x")
    monkeypatch.setenv("DEMO_PUBLIC_BASE_URL", "https://demo.esimerkki.fi/")
    config = load_r2_config()
    assert config is not None
    assert config.endpoint_url == "https://x.r2.cloudflarestorage.com"
    # Oma domain = pelkkä env-muutos; kauttaviiva lopussa ei haittaa
    assert config.public_url("TOKEN") == "https://demo.esimerkki.fi/TOKEN"

    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "")
    assert load_r2_config() is None


def test_config_rejects_non_https_base(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.setenv(key, "x")
    monkeypatch.setenv("DEMO_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    assert load_r2_config() is None


def test_object_key() -> None:
    assert object_key("abc") == "demos/abc.html"


def test_r2_client_settings() -> None:
    from app.demo_publish import R2ObjectStore
    client = R2ObjectStore(CONFIG)._client
    assert client.meta.endpoint_url == "https://acc.r2.cloudflarestorage.com"
    assert client.meta.region_name == "auto"


# --- Julkaisu ---

def test_publish_not_configured_is_503(client_a: TestClient, demo: dict[str, Any]) -> None:
    res = client_a.post(f"/leads/{demo['lead_id']}/demo/publish")
    assert res.status_code == 503
    assert client_a.get(f"/leads/{demo['lead_id']}/demo").json()["status"] == "draft"


def test_publish_uploads_html_and_sets_expiry(client_a: TestClient, demo: dict[str, Any], store: FakeStore) -> None:
    published = _publish(client_a, demo)
    assert published["status"] == "published"
    assert published["public_url"] == f"{PUBLIC_BASE}/{demo['public_token']}"
    assert published["publishing_enabled"] is True
    assert published["preview_url"].startswith("http://testserver/demo/")

    body, expires_at = store.objects[f"demos/{demo['public_token']}.html"]
    html = body.decode()
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert "Tämä on luonnos, jonka Palin teki" in html
    assert expires_at is not None
    published_at = datetime.fromisoformat(published["published_at"].replace("Z", "+00:00"))
    assert expires_at - published_at.astimezone(timezone.utc) == timedelta(days=30)


def test_publish_upload_failure_keeps_draft(client_a: TestClient, demo: dict[str, Any], store: FakeStore) -> None:
    store.fail_put = True
    assert client_a.post(f"/leads/{demo['lead_id']}/demo/publish").status_code == 502
    assert client_a.get(f"/leads/{demo['lead_id']}/demo").json()["status"] == "draft"


def test_publish_blocked_for_do_not_contact(client_a: TestClient, demo: dict[str, Any], store: FakeStore) -> None:
    client_a.patch(f"/leads/{demo['lead_id']}", json={"do_not_contact": True})
    assert client_a.post(f"/leads/{demo['lead_id']}/demo/publish").status_code == 409
    assert store.objects == {}


def test_other_user_cannot_publish(client_b: TestClient, demo: dict[str, Any], store: FakeStore) -> None:
    assert client_b.post(f"/leads/{demo['lead_id']}/demo/publish").status_code == 404
    assert client_b.post(f"/leads/{demo['lead_id']}/demo/unpublish").status_code == 404
    assert store.objects == {}


def test_edit_of_published_demo_updates_same_url(client_a: TestClient, demo: dict[str, Any], store: FakeStore) -> None:
    published = _publish(client_a, demo)
    edited = {k: v for k, v in published["content"].items() if k not in ("opening_hours", "images")}
    edited["hero_subtitle"] = "Uusi alaotsikko joka päivittyy julkaistuun versioon."
    res = client_a.patch(f"/leads/{demo['lead_id']}/demo", json={"content": edited}).json()
    assert res["public_url"] == published["public_url"]
    body, expires_at = store.objects[f"demos/{demo['public_token']}.html"]
    assert "Uusi alaotsikko" in body.decode()
    assert expires_at is not None  # vanhenemisaika säilyy


def test_edit_upload_failure_is_502_and_not_saved(client_a: TestClient, demo: dict[str, Any], store: FakeStore) -> None:
    _publish(client_a, demo)
    store.fail_put = True
    res = client_a.patch(f"/leads/{demo['lead_id']}/demo", json={"template": "services"})
    assert res.status_code == 502
    assert client_a.get(f"/leads/{demo['lead_id']}/demo").json()["template"] == "beauty"


def test_regenerate_published_demo_republishes(
    client_a: TestClient, demo: dict[str, Any], store: FakeStore, fake_openai: type[FakeOpenAI]
) -> None:
    _publish(client_a, demo)
    res = client_a.post(f"/leads/{demo['lead_id']}/demo", json={"template": "services"}).json()
    assert res["status"] == "published"
    assert "#1d5d8c" in store.objects[f"demos/{demo['public_token']}.html"][0].decode()  # services/ocean


def test_unpublish_deletes_object(client_a: TestClient, demo: dict[str, Any], store: FakeStore) -> None:
    _publish(client_a, demo)
    res = client_a.post(f"/leads/{demo['lead_id']}/demo/unpublish").json()
    assert res["status"] == "draft" and res["public_url"] is None and res["expires_at"] is None
    assert store.deleted == [f"demos/{demo['public_token']}.html"]


def test_unpublish_failure_is_502(client_a: TestClient, demo: dict[str, Any], store: FakeStore) -> None:
    _publish(client_a, demo)
    store.fail_delete = True
    assert client_a.post(f"/leads/{demo['lead_id']}/demo/unpublish").status_code == 502
    assert client_a.get(f"/leads/{demo['lead_id']}/demo").json()["status"] == "published"


@pytest.mark.parametrize("how", ["delete_demo", "delete_lead"])
def test_deleting_published_demo_removes_from_r2(
    client_a: TestClient, demo: dict[str, Any], store: FakeStore, how: str
) -> None:
    _publish(client_a, demo)
    path = f"/leads/{demo['lead_id']}/demo" if how == "delete_demo" else f"/leads/{demo['lead_id']}"
    assert client_a.delete(path).status_code == 200
    assert store.deleted == [f"demos/{demo['public_token']}.html"]


def test_delete_draft_does_not_touch_r2(client_a: TestClient, demo: dict[str, Any], store: FakeStore) -> None:
    client_a.delete(f"/leads/{demo['lead_id']}/demo")
    assert store.deleted == []


# --- Vanheneminen ---

def _set_expiry(session: Session, when: datetime) -> Demo:
    row = session.exec(select(Demo)).one()
    row.expires_at = when
    session.add(row)
    session.commit()
    return row


def test_expiry_removes_non_hired_demo(
    client_a: TestClient, demo: dict[str, Any], store: FakeStore, session: Session, engine: Engine
) -> None:
    _publish(client_a, demo)
    _set_expiry(session, datetime.now(timezone.utc) - timedelta(minutes=1))
    assert run_demo_expiry(bind=engine) == {"expired": 1, "extended": 0, "failed": 0}
    assert store.deleted == [f"demos/{demo['public_token']}.html"]
    assert client_a.get(f"/leads/{demo['lead_id']}/demo").json()["status"] == "expired"
    assert client_a.get(f"/demo/{demo['public_token']}").status_code == 410


def test_expiry_extends_hired_demo(
    client_a: TestClient, demo: dict[str, Any], store: FakeStore, session: Session, engine: Engine
) -> None:
    _publish(client_a, demo)
    client_a.patch(f"/leads/{demo['lead_id']}", json={"pipeline_status": "Hired"})
    now = datetime.now(timezone.utc)
    _set_expiry(session, now - timedelta(minutes=1))
    assert run_demo_expiry(now=now, bind=engine) == {"expired": 0, "extended": 1, "failed": 0}
    assert store.deleted == []
    _, new_expiry = store.objects[f"demos/{demo['public_token']}.html"]
    assert new_expiry == now + timedelta(days=30)
    assert client_a.get(f"/leads/{demo['lead_id']}/demo").json()["status"] == "published"


def test_expiry_ignores_future_and_draft(
    client_a: TestClient, demo: dict[str, Any], store: FakeStore, session: Session, engine: Engine
) -> None:
    assert run_demo_expiry(bind=engine) == {"expired": 0, "extended": 0, "failed": 0}  # luonnos
    _publish(client_a, demo)
    assert run_demo_expiry(bind=engine) == {"expired": 0, "extended": 0, "failed": 0}  # ei vielä vanha


def test_expiry_marks_expired_even_if_r2_delete_fails(
    client_a: TestClient, demo: dict[str, Any], store: FakeStore, session: Session, engine: Engine
) -> None:
    _publish(client_a, demo)
    _set_expiry(session, datetime.now(timezone.utc) - timedelta(minutes=1))
    store.fail_delete = True
    # Worker palauttaa 410 expires-at-metadatan perusteella, vaikka objekti jäisi
    assert run_demo_expiry(bind=engine) == {"expired": 1, "extended": 0, "failed": 1}


def test_expiry_without_r2_config_is_noop(engine: Engine) -> None:
    assert run_demo_expiry(bind=engine) == {"expired": 0, "extended": 0, "failed": 0}


# --- Sähköposti ---

def test_email_link_only_for_published_demo(
    client_a: TestClient, demo: dict[str, Any], store: FakeStore, fake_openai: type[FakeOpenAI]
) -> None:
    lead_id = demo["lead_id"]
    fake_openai.reply = "Hei,\n\nVoin tehdä teille ilmaisen luonnoksen.\n\nKiinnostaisiko?"
    draft_email = client_a.post(f"/leads/{lead_id}/generate-email", json={}).json()["body"]
    assert "/demo/" not in draft_email and PUBLIC_BASE not in draft_email
    assert "TARJOUS: Voin tehdä teille ilmaisen luonnoksen" in fake_openai.calls[-1]["messages"][1]["content"]

    published = _publish(client_a, demo)
    fake_openai.reply = "Hei,\n\nTein teille valmiin luonnoksen, voitte katsoa sen täältä: [DEMO_LINKKI]\n\nKiinnostaisiko?"
    body = client_a.post(f"/leads/{lead_id}/generate-email", json={}).json()["body"]
    assert f"voitte katsoa sen täältä: {published['public_url']}" in body
    assert "testserver" not in body and "[DEMO_LINKKI]" not in body
    assert "TARJOUS: Tein teille valmiin luonnoksen" in fake_openai.calls[-1]["messages"][1]["content"]

    client_a.post(f"/leads/{lead_id}/demo/unpublish")
    fake_openai.reply = "Hei,\n\nTein luonnoksen: [DEMO_LINKKI]"
    after = client_a.post(f"/leads/{lead_id}/generate-email", json={}).json()["body"]
    assert PUBLIC_BASE not in after and "[DEMO_LINKKI]" not in after


def test_email_demo_link_added_by_code_if_model_drops_placeholder(
    client_a: TestClient, demo: dict[str, Any], store: FakeStore, fake_openai: type[FakeOpenAI]
) -> None:
    published = _publish(client_a, demo)
    fake_openai.reply = "Hei,\n\nTein teille luonnoksen, katsokaa: https://keksitty.example/abc\n\nKiinnostaisiko?"
    body = client_a.post(f"/leads/{demo['lead_id']}/generate-email", json={}).json()["body"]
    assert "keksitty.example" not in body
    assert f"Luonnos: {published['public_url']}" in body
