# FILE: backend/app/models.py
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field

# Pipeline-statukset (liidin myyntivaihe)
# Shortlisted -> Contacted -> Proposal Received -> Hired | Rejected
PIPELINE_STATUSES = ["Shortlisted", "Contacted", "Proposal Received", "Hired", "Rejected"]

# Nettisivu-statukset (tekninen tila, backendin analyze_website palauttaa naita)
WEBSITE_STATUSES = ["NO WEBSITE", "BROKEN WEBSITE", "NOT MOBILE", "WEBSITE OK"]

class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    google_place_id: Optional[str] = Field(default=None, index=True, unique=True)

    name: str
    city: str = Field(index=True)
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    website_status: Optional[str] = None  # NO WEBSITE | BROKEN WEBSITE | WEBSITE OK

    pipeline_status: str = Field(default="Shortlisted", index=True)
    source: str = Field(default="API")  # API tai MANUAL
    notes: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

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