import os

# Asetetaan ennen app-importtia: database.py ja main.py lukevat envin importissa,
# ja load_dotenv ei ylikirjoita jo asetettuja arvoja -> backend/.env:n oikeat
# avaimet / Supabase-URL eivät vuoda testeihin.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["USE_LIVE_GOOGLE"] = "false"
os.environ["AUTH_DISABLED"] = "false"
os.environ["GOOGLE_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_JWT_SECRET"] = ""
for _smtp_var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
    os.environ[_smtp_var] = ""

from collections.abc import Iterator  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from fastapi import Header  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from app.auth import AuthUser, verify_token  # noqa: E402
from app.database import get_session  # noqa: E402
from app.main import app  # noqa: E402

USER_A = "user-a"
USER_B = "user-b"


class NetworkBlocked(RuntimeError):
    pass


def _blocked(*_args: Any, **_kwargs: Any) -> None:
    raise NetworkBlocked("Oikea verkkokutsu testissä — mockaa se")


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estää oikeat kutsut Googleen, scrapingiin, OpenAI:hin ja SMTP:hen.

    Yksittäinen testi voi ylikirjoittaa näistä tarvitsemansa omalla mockillaan.
    """
    monkeypatch.setattr("requests.get", _blocked)
    monkeypatch.setattr("requests.post", _blocked)
    monkeypatch.setattr("smtplib.SMTP", _blocked)
    monkeypatch.setattr("openai.OpenAI", _blocked)
    monkeypatch.setattr("app.main.scrape_website_text", _blocked)
    monkeypatch.setattr("time.sleep", lambda _s: None)


@pytest.fixture
def engine() -> Iterator[Engine]:
    # StaticPool: sama in-memory-kanta kaikille yhteyksille ja säikeille (asyncio.to_thread)
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    yield test_engine
    SQLModel.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture
def _overrides(engine: Engine) -> Iterator[None]:
    def _get_test_session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    # Käyttäjä valitaan headerilla, jotta samassa testissä voi toimia user A:na ja B:nä
    def _test_user(x_test_user: str = Header(...)) -> AuthUser:
        return AuthUser(id=x_test_user, email=f"{x_test_user}@test", role="authenticated")

    app.dependency_overrides[get_session] = _get_test_session
    app.dependency_overrides[verify_token] = _test_user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client_a(_overrides: None) -> TestClient:
    return TestClient(app, headers={"X-Test-User": USER_A})


@pytest.fixture
def client_b(_overrides: None) -> TestClient:
    return TestClient(app, headers={"X-Test-User": USER_B})


@pytest.fixture
def make_lead(client_a: TestClient) -> Any:
    def _make(client: TestClient | None = None, **fields: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": "Parturi Testi", "city": "Espoo", **fields}
        res = (client or client_a).post("/leads", json=payload)
        assert res.status_code == 200, res.text
        return res.json()

    return _make


class FakeOpenAI:
    """Korvaa openai.OpenAI:n. Tallentaa saadut viestit tarkistusta varten."""

    calls: list[dict[str, Any]] = []
    reply: str = "  Hei, testiviesti.  "

    def __init__(self, api_key: str) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        FakeOpenAI.calls.append(kwargs)
        return SimpleNamespace(
            model="gpt-4o-mini-test",
            choices=[SimpleNamespace(message=SimpleNamespace(content=FakeOpenAI.reply))],
        )


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch) -> type[FakeOpenAI]:
    FakeOpenAI.calls = []
    FakeOpenAI.reply = "  Hei, testiviesti.  "
    monkeypatch.setattr("app.main.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    return FakeOpenAI


TEST_PROFILE: dict[str, Any] = {
    "name": "Palin",
    "company_name": "",
    "phone": "040 123 4567",
    "website": "https://palin.fi",
    "short_intro": "teen nettisivuja paikallisille yrityksille pääkaupunkiseudulla",
}


@pytest.fixture
def sender_profile(client_a: TestClient) -> dict[str, Any]:
    res = client_a.put("/sender-profile", json=TEST_PROFILE)
    assert res.status_code == 200, res.text
    return res.json()
