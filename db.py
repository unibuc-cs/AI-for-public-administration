# db.py
# SQLModel-powered SQLite persistence for:
#  - Cases, Payments, Signatures, Notifications
#  - Uploaded files (metadata only, path + OCR text)
#  - HITL Tasks
#  - CEI-HUB slots and appointments (optional but included)
#
# Provides init_db() to create tables on startup and get_session() if you
# want to use dependency injection style sessions later.

from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session
import uuid

# SQLite database URL; change to a file path as needed
DB_URL = "sqlite:///./mcp_demo.db"
engine = create_engine(DB_URL, echo=False)


# --------------------------- TABLE MODELS ---------------------------

def getRandomSessionId():
    sid = uuid.uuid4().hex
    return sid

class Case(SQLModel, table=True):
    """
    Represents an application/case for CI (CEI/CIS/CIP).
    'case_id' is the public identifier (UUID string), separate from internal PK.
    person_json and payload_json store raw JSON strings for flexibility.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: str
    type: str
    status: str
    person_json: str
    payload_json: str



class Payment(SQLModel, table=True):
    """
    Records payment confirmation metadata.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: str
    amount: float
    status: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Signature(SQLModel, table=True):
    """
    Records a digital signature action on a given case.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: str
    doc_id: Optional[str]
    status: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Notification(SQLModel, table=True):
    """
    Stores email or SMS notification payloads sent to the applicant.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str  # email | sms
    to: str
    subject: Optional[str]
    body: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Upload(SQLModel, table=True):
    """
    Metadata about uploaded files (session-aware) for UI preview and audit.
    Stores OCR text + extracted entities JSON per document.
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    # session linkage
    session_id: str

    # file info
    filename: str
    path: str
    thumb: Optional[str] = None
    size: Optional[int] = None

    # doc kind + OCR raw text
    kind: Optional[str] = None
    ocr_text: Optional[str] = None

    # extracted entities
    extracted_json: Optional[str] = None  # JSON string
    status: Optional[str] = None          # ok | needs_review | failed

    # timestamps when uploaded/processed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Task(SQLModel, table=True):
    """
    Human-in-the-loop task item assigned by the system (e.g., document review).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: str
    kind: str              # DOC_REVIEW | ADDRESS_CHECK | MANUAL_VERIFY ...
    status: str           # OPEN | ASSIGNED | DONE
    assignee: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    """Minimal audit log table for prototype traceability."""
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    actor: str  # user / operator / system
    action: str
    entity_type: str = ""  # case | upload | task | appt | ...
    entity_id: str = ""
    details_json: str = "{}"


class HubSlot(SQLModel, table=True):
    """
    CEI-HUB available slot registry. Seeded with a rolling weekly schedule.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    slot_id: str
    location_id: str
    when: str


# --- SocialSlot model (AS program slots) ---
class SocialSlot(SQLModel, table=True):
    id: str = Field(primary_key=True)
    location_id: str
    when: datetime



class HubAppt(SQLModel, table=True):
    """
    CEI-HUB appointment record. Created when a slot is reserved.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    appt_id: str
    when: str
    location: str


# --------------------------- HELPERS ---------------------------

def init_db():
    """
    Create tables if they don't exist yet.
    """
    SQLModel.metadata.create_all(engine)


def get_session():
    """
    Generator function that yields a Session for DI patterns
    (unused in current code but available).
    """
    with Session(engine) as s:
        yield s
