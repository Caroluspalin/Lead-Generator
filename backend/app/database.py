# FILE: backend/app/database.py
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine, Session

# Lataa .env backend/-kansiosta
_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///agency_hunter.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=True, connect_args=connect_args)

def get_session():
    with Session(engine) as session:
        yield session

def create_db_and_tables():
    """Luo taulut tietokantaan automaattisesti käynnistyksessä"""
    SQLModel.metadata.create_all(engine)