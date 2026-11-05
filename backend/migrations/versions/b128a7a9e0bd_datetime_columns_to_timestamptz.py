"""datetime columns to timestamptz

Revision ID: b128a7a9e0bd
Revises: ab965e378f8b
Create Date: 2026-11-05 22:55:22.501928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b128a7a9e0bd'
down_revision: Union[str, Sequence[str], None] = 'ab965e378f8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kaikki mallien datetime-sarakkeet. Vanhat Supabase-taulut luotiin create_all:lla
# SQLModel 0.0.32:lla -> TIMESTAMP WITHOUT TIME ZONE, arvot naiiveja UTC-aikoja.
DATETIME_COLUMNS: list[tuple[str, str]] = [
    ("emaildraft", "created_at"),
    ("lead", "scraped_at"),
    ("lead", "created_at"),
    ("lead", "updated_at"),
    ("searchhistoryentry", "searched_at"),
]


def _naive_timestamp_columns(conn: sa.Connection) -> list[tuple[str, str]]:
    rows = conn.execute(
        sa.text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND data_type = 'timestamp without time zone'"
        )
    ).all()
    naive = {(r[0], r[1]) for r in rows}
    return [c for c in DATETIME_COLUMNS if c in naive]


def upgrade() -> None:
    """TIMESTAMP -> TIMESTAMPTZ Postgresissa. SQLite: no-op (ei aikavyöhyketyyppiä)."""
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    # Vain naiivit sarakkeet: Alembicilla luodut kannat ovat jo timestamptz, ja niille
    # "AT TIME ZONE 'UTC'" siirtäisi arvoja session aikavyöhykkeen verran.
    for table, column in _naive_timestamp_columns(conn):
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
            f"TYPE TIMESTAMP WITH TIME ZONE USING \"{column}\" AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    """TIMESTAMPTZ -> TIMESTAMP (naiivi UTC). SQLite: no-op."""
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    for table, column in DATETIME_COLUMNS:
        op.execute(
            f'ALTER TABLE "{table}" ALTER COLUMN "{column}" '
            f"TYPE TIMESTAMP WITHOUT TIME ZONE USING \"{column}\" AT TIME ZONE 'UTC'"
        )
