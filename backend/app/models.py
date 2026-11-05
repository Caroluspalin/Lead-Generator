# FILE: backend/app/models.py
from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

# Pipeline-statukset (liidin myyntivaihe)
# Shortlisted -> Contacted -> Proposal Received -> Hired | Rejected
PIPELINE_STATUSES = ["Shortlisted", "Contacted", "Proposal Received", "Hired", "Rejected"]

# Nettisivu-statukset (tekninen tila, backendin analyze_website palauttaa naita)
WEBSITE_STATUSES = ["NO WEBSITE", "BROKEN WEBSITE", "NOT MOBILE", "WEBSITE OK"]

class SearchHistoryEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    business_type: str
    city: str
    result_count: int = 0
    searched_at: datetime = Field(default_factory=utc_now)


class EmailDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    lead_id: int = Field(index=True)
    subject: str
    body: str
    model: str
    created_at: datetime = Field(default_factory=utc_now)


class Lead(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("google_place_id", "user_id", name="uq_lead_place_user"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    google_place_id: Optional[str] = Field(default=None, index=True)

    name: str
    city: str = Field(index=True)
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    website_status: Optional[str] = None  # NO WEBSITE | BROKEN WEBSITE | WEBSITE OK

    # Deep Scan: skraapattu verkkosivun konteksti personointia varten
    website_context: Optional[str] = None
    scraped_at: Optional[datetime] = None

    pipeline_status: str = Field(default="Shortlisted", index=True)
    source: str = Field(default="API")  # API tai MANUAL
    notes: Optional[str] = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class LeadCreate(SQLModel):
    name: str
    city: str
    google_place_id: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    website_status: Optional[str] = None
    pipeline_status: str = "Shortlisted"
    source: str = "API"

class LeadUpdate(SQLModel):
    pipeline_status: Optional[str] = None
    notes: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
