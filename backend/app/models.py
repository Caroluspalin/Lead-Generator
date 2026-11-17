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
WEBSITE_STATUSES = ["NO WEBSITE", "BROKEN WEBSITE", "INSECURE", "NOT MOBILE", "WEBSITE OK", "UNKNOWN"]

class SearchHistoryEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    business_type: str
    city: str
    result_count: int = 0
    searched_at: datetime = Field(default_factory=utc_now)


# Käyttäjän näkemä tila Google-paikalle. Vain place_id ja tila: Googlen ehdot sallivat place_id:n
# pysyvän tallennuksen, muuta Places-sisältöä ei tallenneta tähän tauluun.
PLACE_STATUSES = ["seen", "in_pipeline", "dismissed"]


class PlaceStatus(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("user_id", "place_id", name="uq_placestatus_user_place"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    place_id: str
    status: str
    updated_at: datetime = Field(default_factory=utc_now)


class EmailDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    lead_id: int = Field(index=True)
    subject: str
    body: str
    model: str
    created_at: datetime = Field(default_factory=utc_now)


# Demo-sivun tila: draft = vain paikallinen esikatselu, published = julkaistu (Vaihe B), expired = vanhentunut
DEMO_STATUSES = ["draft", "published", "expired"]


class Demo(SQLModel, table=True):
    # Yksi demo per liidi. Uudelleengenerointi päivittää saman rivin ja säilyttää public_tokenin,
    # jotta jo lähetetty linkki pysyy toimivana.
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    lead_id: int = Field(index=True, unique=True)
    template: str
    color_scheme: str
    content_json: str  # DemoStoredContent JSONina (sis. generointihetken aukioloajat)
    html: str
    public_token: str = Field(index=True, unique=True)
    # Luettava osoite (/taina-lantiainen-k7x2m). None = demo luotu ennen slugeja: osoite on token,
    # jotta jo lähetetyt linkit ja R2-objektit pysyvät ennallaan. Ei muutu uudelleengeneroinnissa.
    public_slug: Optional[str] = Field(default=None, index=True, unique=True)
    status: str = Field(default="draft")
    created_at: datetime = Field(default_factory=utc_now)
    published_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class DemoOpen(SQLModel, table=True):
    # Julkaistun demon avaus (Worker kirjaa R2:een, POST /leads/sync-opens tuo tänne). Vain aika ja laite.
    # slot = Workerin 10 min ämpäri: sama demo + laite + ämpäri on yksi avaus (idempotentti tuonti).
    __table_args__ = (UniqueConstraint("demo_id", "slot", "device", name="uq_demoopen_slot"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    demo_id: int = Field(index=True)
    user_id: str = Field(index=True)
    opened_at: datetime
    device: str
    slot: int


# Sarjan tila: draft = ei vielä hyväksytty (mitään ei lähde), active = hyväksytty, stopped / replied / completed = päättynyt
SEQUENCE_STATUSES = ["draft", "active", "stopped", "replied", "completed"]
OPEN_SEQUENCE_STATUSES = ["draft", "active"]
# Askeleen tila. sending = lukittu lähetykseen (ei koskaan lähetetä uudelleen automaattisesti), needs_review = ihmisen tarkistettava
STEP_STATUSES = ["scheduled", "sending", "sent", "stopped", "replied", "failed", "needs_review"]


class FollowUpSequence(SQLModel, table=True):
    # Yksi sähköpostisarja liidille: askel 0 = aloitusviesti, 1..n = seurantaviestit
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    lead_id: int = Field(index=True)
    status: str = Field(default="draft", index=True)
    stop_reason: Optional[str] = None  # replied / dnc / opt_out / bounced / manual / demo_expired / resent
    approved_at: Optional[datetime] = None
    replied_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class FollowUpStep(SQLModel, table=True):
    # Ajastettu lähetys. message_id tallennetaan ennen SMTP-kutsua (vastausten tunnistus + tupla-esto).
    __table_args__ = (UniqueConstraint("sequence_id", "step_no", name="uq_followupstep_seq_no"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    sequence_id: int = Field(index=True)
    lead_id: int = Field(index=True)
    step_no: int
    subject: str
    body: str
    model: str = ""
    # Demolinkki, jonka viesti sisältää: jos demo ei ole enää julkaistu, askel ei lähde (needs_review)
    demo_url: Optional[str] = None
    to_email: Optional[str] = None
    due_at: Optional[datetime] = None
    status: str = Field(default="scheduled", index=True)
    message_id: Optional[str] = Field(default=None, index=True)
    claimed_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    attempts: int = 0
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class MailboxState(SQLModel, table=True):
    # IMAP-tilin lukukohta. Postilaatikko on koko palvelun resurssi, ei yhden käyttäjän data, joten avain on tili.
    id: Optional[int] = Field(default=None, primary_key=True)
    account: str = Field(unique=True, index=True)
    uidvalidity: Optional[int] = None
    last_uid: int = 0
    checked_at: Optional[datetime] = None


class SenderProfile(SQLModel, table=True):
    # Yksi per käyttäjä: lähettäjän tiedot sähköposti- ja puhelinprompteihin + allekirjoitus
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, unique=True)
    name: str
    company_name: Optional[str] = None
    # Allekirjoituksessa näkyvä nimi (esim. "Palin Web"); company_name voi olla virallinen (Tmi ...)
    brand_name: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None  # portfolio
    short_intro: str  # esim. "teen nettisivuja paikallisille yrityksille Espoossa"
    updated_at: datetime = Field(default_factory=utc_now)


class SenderProfileUpdate(SQLModel):
    name: str = Field(min_length=1, max_length=100)
    company_name: Optional[str] = Field(default=None, max_length=100)
    brand_name: Optional[str] = Field(default=None, max_length=60)
    phone: Optional[str] = Field(default=None, max_length=40)
    website: Optional[str] = Field(default=None, max_length=200)
    short_intro: str = Field(min_length=5, max_length=200)


class LeadBase(SQLModel):
    # Yhteiset kentät: Lead (taulu) ja LeadRead (GET /leads, lisäksi laskettu demo_published)
    user_id: str = Field(index=True)
    google_place_id: Optional[str] = Field(default=None, index=True)

    name: str
    city: str = Field(index=True)
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    website_status: Optional[str] = None  # ks. WEBSITE_STATUSES
    website_issue: Optional[str] = None   # lyhyt syy, esim. "SSL certificate expired", "HTTP 500"

    # Deep Scan: skraapattu verkkosivun konteksti personointia varten
    website_context: Optional[str] = None
    scraped_at: Optional[datetime] = None
    # Laajennettu skannaus (app/utils/site_content.py): palvelut, hinnat ja esittely JSONina (SiteFacts).
    # Tyhjä JSON = skannattu ilman käyttökelpoista sisältöä (ei skannata uudelleen joka demolla)
    website_facts: Optional[str] = None
    website_facts_at: Optional[datetime] = None
    # Timma-tuonti (app/utils/timma.py): TimmaSnapshot JSONina + hakupäivä. Haetaan kerran, uudelleen vain Refreshistä
    timma_data: Optional[str] = None
    timma_fetched_at: Optional[datetime] = None
    # Ostosignaalit (app/utils/signals.py): PageSpeed Insights -mittaus (mobiili) ja sivun ©-vuosi.
    # Vain mitattu/luettu arvo, tyhjä = ei mitattu
    pagespeed_lcp_s: Optional[float] = None
    pagespeed_score: Optional[int] = None
    pagespeed_at: Optional[datetime] = None
    site_copyright_year: Optional[int] = None
    # Autodemo julkaisi demon automaattisesti: tarkista demo ennen yhteydenottoa
    review_before_contact: bool = Field(default=False)

    # Yhteystiedot: vain sivustolta oikeasti löytynyt osoite (app/utils/contact_finder.py)
    email: Optional[str] = None
    email_source: Optional[str] = None  # esim. "mailto on /yhteystiedot"
    do_not_contact: bool = Field(default=False)

    # Places API (New) -tiedot hakuhetkeltä + pisteytys (app/scoring.py)
    rating: Optional[float] = None
    review_count: Optional[int] = None
    business_status: Optional[str] = None  # OPERATIONAL | CLOSED_TEMPORARILY
    primary_type: Optional[str] = None
    maps_url: Optional[str] = None
    lead_score: Optional[int] = Field(default=None, index=True)

    pipeline_status: str = Field(default="Shortlisted", index=True)
    source: str = Field(default="API")  # API tai MANUAL
    notes: Optional[str] = None

    # Diilin arvo euroina: syötetään käsin, ei päätellä mistään
    deal_value: Optional[int] = None  # kertaluontoinen
    recurring_monthly: Optional[int] = None  # ylläpito €/kk

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Lead(LeadBase, table=True):
    __table_args__ = (
        UniqueConstraint("google_place_id", "user_id", name="uq_lead_place_user"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)


class LeadRead(LeadBase):
    id: int
    # Laskettu Demo-taulusta (ei saraketta): julkaistu ja voimassa oleva demo
    demo_published: bool = False
    # Laskettu DemoOpen-taulusta: liidin julkaistun demon avaukset (ei botteja, ei omia esikatseluja)
    demo_open_count: int = 0
    demo_last_opened_at: Optional[datetime] = None
    # Laskettu FollowUpSequence-taulusta: uusimman sarjan tila ja seuraavan viestin aika
    followup_status: Optional[str] = None
    followup_next_at: Optional[datetime] = None
    followup_replied_at: Optional[datetime] = None

class LeadCreate(SQLModel):
    name: str
    city: str
    google_place_id: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    website_status: Optional[str] = None
    website_issue: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    business_status: Optional[str] = None
    primary_type: Optional[str] = None
    maps_url: Optional[str] = None
    pipeline_status: str = "Shortlisted"
    source: str = "API"

class LeadUpdate(SQLModel):
    pipeline_status: Optional[str] = None
    notes: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    do_not_contact: Optional[bool] = None
    website: Optional[str] = None
    review_before_contact: Optional[bool] = None
    deal_value: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    recurring_monthly: Optional[int] = Field(default=None, ge=0, le=1_000_000)
