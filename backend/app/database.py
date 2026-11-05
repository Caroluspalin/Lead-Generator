# FILE: backend/app/database.py
import os
from pathlib import Path
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

connect_args = {"check_same_thread": False} if _is_sqlite else {}

# Postgres tarvitsee poolin + pre_ping estaakseen timeoutatut yhteydet
if _is_sqlite:
    engine = create_engine(DATABASE_URL, echo=_echo, connect_args=connect_args)
else:
    engine = create_engine(
        DATABASE_URL,
        echo=_echo,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


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
