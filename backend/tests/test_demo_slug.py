"""Luettavat demo-osoitteet: slug nimestä, satunnaisosa, törmäykset, vanhat token-osoitteet."""
import json
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.demo_site import (
    SLUG_ALPHABET,
    SLUG_NAME_MAX,
    SLUG_RE,
    SLUG_SUFFIX_LEN,
    name_slug,
    new_public_slug,
    new_public_token,
    random_slug_suffix,
)
from app.models import Demo
from tests.conftest import FakeOpenAI
from tests.test_demo_publish import CONFIG, PUBLIC_BASE, FakeStore
from tests.test_demo_site import VALID


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Parturi Esimerkki", "parturi-esimerkki"),
        # Pitkästä nimestä pudotetaan yleiset toimialasanat
        ("Parturi-Kampaamo Taina Lantiainen", "taina-lantiainen"),
        ("Autokorjaamo Mäkinen & Pojat Ky", "makinen-pojat"),
        # Ääkköset a/o, å a, aksentit pois, välimerkit väliviivoiksi
        ("Kahvila Säde & Pöllö Oy", "kahvila-sade-pollo"),
        ("Hiusstudio Åsa", "hiusstudio-asa"),
        ("Café Crème", "cafe-creme"),
        ("  Kukka--Kauppa!!  ", "kukka-kauppa"),
        # Yritysmuoto pois aina
        ("Tmi Virtanen", "virtanen"),
        ("Pelkkä Oy Ab", "pelkka"),
        # Ei latinalaisia kirjaimia / pelkkä yritysmuoto -> tyhjä (osoite demo-xxxxx)
        ("東京寿司", ""),
        ("Tmi", ""),
    ],
)
def test_name_slug(name: str, slug: str) -> None:
    assert name_slug(name) == slug


def test_long_name_is_cut_at_word_boundary() -> None:
    slug = name_slug("Kampaamo Hius-Kärkkäinen Helsinki Keskusta Itäkeskus Kontula Malmi")
    assert len(slug) <= SLUG_NAME_MAX
    assert not slug.endswith("-") and "kontul" not in slug.split("-")[-1][:-1]
    assert slug.startswith("hius-karkkainen-helsinki")


def test_only_generic_words_are_kept_rather_than_empty() -> None:
    # Kaikki sanat yleisiä -> ne säilytetään (ei tyhjää), katkaisu sanarajalla 40 merkkiin
    assert name_slug("Parturi Kampaamo Kauneushoitola Hiusstudio") == "parturi-kampaamo-kauneushoitola"


def test_suffix_alphabet_and_length() -> None:
    suffixes = {random_slug_suffix() for _ in range(300)}
    assert all(len(s) == SLUG_SUFFIX_LEN and set(s) <= set(SLUG_ALPHABET) for s in suffixes)
    assert not set("0o1li") & set(SLUG_ALPHABET)  # sekoittuvat merkit pois
    assert len(suffixes) > 290  # käytännössä kaikki erilaisia


def test_new_slug_format() -> None:
    slug = new_public_slug("Parturi-Kampaamo Taina Lantiainen", lambda _s: False)
    assert SLUG_RE.match(slug)
    assert slug.startswith("taina-lantiainen-") and len(slug) == len("taina-lantiainen-") + SLUG_SUFFIX_LEN
    assert new_public_slug("東京寿司", lambda _s: False).startswith("demo-")


def test_collision_gets_new_suffix() -> None:
    suffixes = iter(["aaaaa", "bbbbb", "ccccc"])
    taken = {"parturi-esimerkki-aaaaa", "parturi-esimerkki-bbbbb"}
    slug = new_public_slug("Parturi Esimerkki", lambda s: s in taken, suffix=lambda: next(suffixes))
    assert slug == "parturi-esimerkki-ccccc"


def test_endless_collisions_raise() -> None:
    with pytest.raises(RuntimeError):
        new_public_slug("Parturi Esimerkki", lambda _s: True, suffix=lambda: "aaaaa")


def test_slug_and_token_formats_do_not_overlap() -> None:
    # Token (43 merkkiä base64url) ei koskaan näytä slugilta, joten polkunimiavaruus on yksiselitteinen
    assert not any(SLUG_RE.match(new_public_token()) for _ in range(200))


# --- Endpointit ---

@pytest.fixture
def ready(fake_openai: type[FakeOpenAI], sender_profile: dict[str, Any]) -> type[FakeOpenAI]:
    fake_openai.reply = json.dumps(VALID)
    return fake_openai


def _create(client: TestClient, make_lead: Any, name: str = "Parturi-Kampaamo Taina Lantiainen") -> dict[str, Any]:
    lead = make_lead(name=name, city="Kauniainen", phone="050 5936073", website_status="NO WEBSITE", primary_type="hair_salon")
    res = client.post(f"/leads/{lead['id']}/demo", json={})
    assert res.status_code == 200, res.text
    return res.json()


def test_new_demo_gets_readable_address(client_a: TestClient, make_lead: Any, ready: type[FakeOpenAI]) -> None:
    demo = _create(client_a, make_lead)
    assert SLUG_RE.match(demo["public_path"]) and demo["public_path"].startswith("taina-lantiainen-")
    assert demo["preview_url"] == f"http://testserver/demo/{demo['public_path']}"
    assert client_a.get(f"/demo/{demo['public_path']}").status_code == 200


def test_published_demo_uses_slug_for_url_and_r2_key(
    client_a: TestClient, make_lead: Any, ready: type[FakeOpenAI], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FakeStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: store)
    demo = _create(client_a, make_lead)
    published = client_a.post(f"/leads/{demo['lead_id']}/demo/publish").json()
    assert published["public_url"] == f"{PUBLIC_BASE}/{demo['public_path']}"
    assert list(store.objects) == [f"demos/{demo['public_path']}.html"]
    assert demo["public_token"] not in published["public_url"]


def test_slug_collision_in_database_gets_new_suffix(
    client_a: TestClient, make_lead: Any, ready: type[FakeOpenAI], monkeypatch: pytest.MonkeyPatch
) -> None:
    sequence = count()
    # Kaksi samannimistä yritystä, satunnaisosa toistuu ensin -> toinen saa seuraavan
    monkeypatch.setattr(
        "app.demo_site.random_slug_suffix", lambda: ["aaaaa", "aaaaa", "bbbbb"][min(next(sequence), 2)]
    )
    first = _create(client_a, make_lead, "Parturi Esimerkki")
    second = _create(client_a, make_lead, "Parturi Esimerkki")
    assert first["public_path"] == "parturi-esimerkki-aaaaa"
    assert second["public_path"] == "parturi-esimerkki-bbbbb"


def test_old_token_address_still_works(
    client_a: TestClient, make_lead: Any, ready: type[FakeOpenAI], engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo = _create(client_a, make_lead)
    # Ennen slugeja luotu demo: public_slug puuttuu
    with Session(engine) as s:
        row = s.exec(select(Demo).where(Demo.id == demo["id"])).one()
        row.public_slug = None
        s.add(row)
        s.commit()

    store = FakeStore()
    monkeypatch.setattr("app.main.get_r2_config", lambda: CONFIG)
    monkeypatch.setattr("app.main.get_object_store", lambda: store)
    again = client_a.get(f"/leads/{demo['lead_id']}/demo").json()
    assert again["public_path"] == demo["public_token"]
    assert client_a.get(f"/demo/{demo['public_token']}").status_code == 200
    published = client_a.post(f"/leads/{demo['lead_id']}/demo/publish").json()
    assert published["public_url"] == f"{PUBLIC_BASE}/{demo['public_token']}"
    assert list(store.objects) == [f"demos/{demo['public_token']}.html"]


def test_unknown_or_partial_address_is_404(client_a: TestClient, make_lead: Any, ready: type[FakeOpenAI]) -> None:
    demo = _create(client_a, make_lead)
    prefix = demo["public_path"].rsplit("-", 1)[0]
    for path in [prefix, f"{prefix}-zzzzz", demo["public_path"][:-1], "taina-lantiainen"]:
        assert client_a.get(f"/demo/{path}").status_code == 404, path


def test_worker_accepts_the_same_slug_format() -> None:
    # Worker validoi polun ennen R2-hakua: sen regexin pitää vastata backendin SLUG_RE:tä
    worker = (Path(__file__).resolve().parents[2] / "worker" / "src" / "index.ts").read_text()
    assert f"const SLUG_RE = /{SLUG_RE.pattern}/;" in worker
