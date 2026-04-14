# FILE: backend/app/database.py
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine, Session

# Lataa .env backend/-kansiosta
_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///agency_hunter.db")

# Supabase/Heroku palauttaa "postgres://" — SQLAlchemy 2.x vaatii "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

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


def create_db_and_tables():
    """Luo taulut tietokantaan automaattisesti kaynnistyksessa.

    Toimii tyhjaan Postgres-kantaan: SQLModel.metadata.create_all lisaa
    vain puuttuvat taulut, ei muuta olemassaolevia.
    """
    SQLModel.metadata.create_all(engine)
