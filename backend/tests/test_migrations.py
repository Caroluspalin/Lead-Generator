import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, inspect, text

from app.database import normalize_database_url

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _config(connection: object) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


def test_upgrade_matches_models_and_roundtrips(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'migrations.db'}")
    with engine.begin() as conn:
        cfg = _config(conn)
        command.upgrade(cfg, "head")
        # Kaatuu jos mallit ja migraatiot eroavat (unohtunut migraatio)
        command.check(cfg)

        command.downgrade(cfg, "base")
        assert set(inspect(conn).get_table_names()) == {"alembic_version"}

        command.upgrade(cfg, "head")
        command.check(cfg)
    engine.dispose()


TIMESTAMPTZ_REVISION = "b128a7a9e0bd"
DATETIME_COLUMNS = [
    ("emaildraft", "created_at"),
    ("lead", "scraped_at"),
    ("lead", "created_at"),
    ("lead", "updated_at"),
    ("searchhistoryentry", "searched_at"),
]


def _column_types(conn: Connection) -> dict[tuple[str, str], str]:
    rows = conn.execute(text(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    )).all()
    return {(r[0], r[1]): r[2] for r in rows if (r[0], r[1]) in DATETIME_COLUMNS}


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL ei asetettu")
def test_timestamptz_migration_on_legacy_postgres() -> None:
    """Simuloi vanhaa Supabase-kantaa: naiivit TIMESTAMP-sarakkeet, session TZ ei UTC."""
    engine = create_engine(normalize_database_url(os.environ["TEST_POSTGRES_URL"]))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    with engine.begin() as conn:
        conn.execute(text("SET TIME ZONE 'Europe/Helsinki'"))
        cfg = _config(conn)
        command.upgrade(cfg, "ab965e378f8b")
        for table, column in DATETIME_COLUMNS:
            conn.execute(text(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE TIMESTAMP WITHOUT TIME ZONE'
            ))
        conn.execute(text(
            "INSERT INTO searchhistoryentry (user_id, business_type, city, result_count, searched_at) "
            "VALUES ('u', 'parturi', 'Espoo', 1, '2026-01-15 10:00:00')"
        ))

        command.upgrade(cfg, TIMESTAMPTZ_REVISION)
        assert set(_column_types(conn).values()) == {"timestamp with time zone"}
        utc_value = conn.execute(text(
            "SELECT searched_at AT TIME ZONE 'UTC' FROM searchhistoryentry"
        )).scalar_one()
        assert utc_value.isoformat() == "2026-01-15T10:00:00"

        command.downgrade(cfg, "-1")
        assert set(_column_types(conn).values()) == {"timestamp without time zone"}
        naive = conn.execute(text("SELECT searched_at FROM searchhistoryentry")).scalar_one()
        assert naive.isoformat() == "2026-01-15T10:00:00"

        command.upgrade(cfg, "head")
        command.check(cfg)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="TEST_POSTGRES_URL ei asetettu")
def test_fresh_postgres_upgrade_keeps_timestamptz_values() -> None:
    """Alembicilla luodut sarakkeet ovat jo timestamptz: migraatio ei saa siirtää arvoja."""
    engine = create_engine(normalize_database_url(os.environ["TEST_POSTGRES_URL"]))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    with engine.begin() as conn:
        conn.execute(text("SET TIME ZONE 'Europe/Helsinki'"))
        cfg = _config(conn)
        command.upgrade(cfg, "ab965e378f8b")
        assert set(_column_types(conn).values()) == {"timestamp with time zone"}
        conn.execute(text(
            "INSERT INTO searchhistoryentry (user_id, business_type, city, result_count, searched_at) "
            "VALUES ('u', 'parturi', 'Espoo', 1, '2026-01-15 10:00:00+00')"
        ))

        command.upgrade(cfg, "head")
        assert set(_column_types(conn).values()) == {"timestamp with time zone"}
        utc_value = conn.execute(text(
            "SELECT searched_at AT TIME ZONE 'UTC' FROM searchhistoryentry"
        )).scalar_one()
        assert utc_value.isoformat() == "2026-01-15T10:00:00"
        command.check(cfg)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    engine.dispose()
