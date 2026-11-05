import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.database import normalize_database_url


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
