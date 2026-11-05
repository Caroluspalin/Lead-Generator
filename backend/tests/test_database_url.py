import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.database import engine_options, normalize_database_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@db.example.supabase.co:5432/postgres", "postgresql+psycopg://u:p@db.example.supabase.co:5432/postgres"),
        ("postgresql://u:p@pooler.supabase.com:6543/postgres", "postgresql+psycopg://u:p@pooler.supabase.com:6543/postgres"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg2://u:p@h/db", "postgresql+psycopg2://u:p@h/db"),
        ("sqlite:///agency_hunter.db", "sqlite:///agency_hunter.db"),
        ("sqlite://", "sqlite://"),
    ],
)
def test_normalize_database_url(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected


def test_password_with_postgres_substring_is_untouched() -> None:
    url = "postgres://user:postgres://x@h:5432/db"
    assert normalize_database_url(url) == "postgresql+psycopg://user:postgres://x@h:5432/db"


@pytest.mark.parametrize("raw", ["postgres://u:p@h:5432/db", "postgresql://u:p@h:6543/db"])
def test_normalized_url_resolves_to_psycopg3_driver(raw: str) -> None:
    # create_engine lataa ajurin mutta ei avaa yhteyttä
    url = make_url(normalize_database_url(raw))
    assert url.get_backend_name() == "postgresql"
    assert url.get_driver_name() == "psycopg"
    engine = create_engine(url)
    assert engine.dialect.driver == "psycopg"
    engine.dispose()


def test_postgres_engine_disables_prepared_statements() -> None:
    opts = engine_options(normalize_database_url("postgresql://u:p@pooler.supabase.com:6543/postgres"))
    assert opts["connect_args"] == {"prepare_threshold": None}
    assert opts["pool_pre_ping"] is True


def test_sqlite_engine_has_no_prepare_threshold() -> None:
    opts = engine_options("sqlite:///agency_hunter.db")
    assert opts["connect_args"] == {"check_same_thread": False}
    assert "prepare_threshold" not in opts["connect_args"]


def test_postgres_engine_options_reach_psycopg_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    # Varmistetaan että connect_args todella välittyy psycopg.connect-kutsulle (ilman oikeaa kantaa)
    captured: dict[str, object] = {}

    def _fake_connect(*_args: object, **kwargs: object) -> None:
        captured.update(kwargs)
        raise RuntimeError("ei oikeaa yhteyttä testissä")

    monkeypatch.setattr("psycopg.connect", _fake_connect)
    url = normalize_database_url("postgresql://u:p@127.0.0.1:1/db")
    engine = create_engine(url, **engine_options(url))
    with pytest.raises(RuntimeError):
        engine.connect()
    engine.dispose()
    assert "prepare_threshold" in captured
    assert captured["prepare_threshold"] is None
