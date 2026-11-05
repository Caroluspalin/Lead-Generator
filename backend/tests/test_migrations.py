from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

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
