# FILE: backend/app/database.py
import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine, Session

# Lataa .env backend/-kansiosta
_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env")



def normalize_database_url(url: str) -> str:
    """Pakottaa Postgres-URLit psycopg (v3) -ajuriin.

    Supabase/Heroku antaa "postgres://", jota SQLAlchemy 2.x ei hyväksy, ja pelkkä
    "postgresql://" valitsee ajurin SQLAlchemy-version oletuksen mukaan. Eksplisiittinen
    ajuri jätetään ennalleen.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///agency_hunter.db"))

_is_sqlite = DATABASE_URL.startswith("sqlite")
_echo = os.getenv("SQL_ECHO", "false").lower() == "true"


def engine_options(url: str) -> dict[str, Any]:
    """create_engine-argumentit URL:n mukaan (erillään, jotta testattavissa ilman yhteyttä)."""
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        # Supabase transaction pooler (6543) ei tue prepared statementeja; psycopg3
        # alkaa käyttää niitä automaattisesti 5. toistetun kyselyn jälkeen
        "connect_args": {"prepare_threshold": None},
        # Pool + pre_ping estää timeoutatut yhteydet
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
    }


engine = create_engine(DATABASE_URL, echo=_echo, **engine_options(DATABASE_URL))


def get_session():
    with Session(engine) as session:
        yield session


def create_db_and_tables() -> None:
    """Dev-SQLite: luo puuttuvat taulut käynnistyksessä kuten ennenkin.

    Postgresissa (tuotanto) skeema hallitaan vain Alembicilla (`alembic upgrade head`),
    koska create_all ei muuta olemassa olevia tauluja eikä jätä migraatiohistoriaa.
    """
    if not _is_sqlite:
        return
    SQLModel.metadata.create_all(engine)
