# TODO: MOVE the operator operations to operator_agent. Similar possibly for others!

""""
Note: A2A architecture (graph.py). The “brain” no longer hardcodes all logic in one giant if.

Each agent is a small service that:
    1. reads the shared state
    2. does one thing
    3. writes back to shared state
    4. tells who should run next (state["next_agent"] = "...")

That’s agent-to-agent chaining — you can later move one of these agents into another process (MCP, separate FastAPI, LangServe) and keep the same pattern.
"""


# agents/orchestrator.py
# Orchestrator API that:
#  - Provides a /api/chat endpoint to drive the "MCP-like" flow
#  - Exposes /api/reschedule and /api/cancel endpoints for CEI appointments
#  - Includes a /api/search endpoint to query the RAG index (debug/testing)
#
# The chat endpoint ties together all tools:
#   eligibility -> docs -> case -> payment -> signature -> scheduling -> notify
#
# NOTE: The OpenAI model is not directly called here

""" PLAN:
Chat: The /api/chat handler is place to plug in OpenAI (or LangChain/LangGraph)
Parse intents (e.g., “start CI” → return link to /user-ci).
Answer knowledge questions using RAG (agents/rag.py).
Route to tool calls (validate/create/schedule).
Agents / MCP: Each operation is already a tool (agents/tools.py). Wrapping them with MCP or LangChain Tools is straightforward: define tool schemas and call the same functions.
State: Keep the case creation separate from scheduling; rescheduling remains via /api/reschedule.
"""

import os, json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter
from pydantic import BaseModel
from agents.graph import run_agent_graph
import httpx
import re

# Import tools (side-effect functions) and RAG helper
from agents.tools import (
    tool_eligibility, tool_docs_required, tool_docs_missing,
    tool_case_submit, tool_payment, tool_signature, tool_schedule,
    tool_reschedule, tool_cancel_appointment, tool_upload,
    tool_notify_email, tool_notify_sms, tool_schedule_by_slot
)
from agents import rag

router = APIRouter()

class ChatIn(BaseModel):
    session_id: str
    message: str
    person: Optional[dict] = None
    application: Optional[dict] = None

# Simple in-memory session storage (conversation history)
SESSIONS: Dict[str, List[Dict[str, Any]]] = {}

SESS_STATE: Dict[str, Dict[str, Any]] = {}   # per-session lightweight FSM state

def _state(sid: str) -> Dict[str, Any]:
    """Ensure & return state for session."""
    if sid not in SESS_STATE:
        SESS_STATE[sid] = {
            "phase": "idle",
            "person": {},
            "app": {"type": "auto", "eligibility_reason": "EXP_60", "docs": []},
            "missing": [],
            "decided_type": None,
        }
    return SESS_STATE[sid]



def _doc_synonyms() -> Dict[str, str]:
    """Map user text tokens to canonical doc kinds used by tools."""
    return {
        r"\b(certificat(?:ul)? de n(a|ă)stere|cert[ ._-]?nastere)\b": "cert_nastere",
        r"\b(ci(?: veche)?|buletin(?:ul)? vechi)\b": "ci_veche",
        r"\b(dovad(a|ă) (?:de )?adres(a|ă)|extras(?:ul)? cf|contract(?:ul)?(?: de inchiriere)?)\b": "dovada_adresa",
        r"\b(poli(t|ț)ie|furt|pierdere)\b": "politie",
    }


def _mark_doc_present(app: Dict[str, Any], doc_kind: str) -> None:
    """Idempotently mark a doc as present in app['docs']."""
    docs = app.setdefault("docs", [])
    if not any(d.get("kind") == doc_kind for d in docs):
        docs.append({"kind": doc_kind, "status": "ok"})


# --------------------------- MODELS ---------------------------

class Person(BaseModel):
    """
    Minimal person profile received from the UI.
    """
    cnp: str
    nume: str
    prenume: str
    email: str
    telefon: str
    domiciliu: Dict[str, Any]


class Doc(BaseModel):
    """
    Document descriptor used for doc intake checks.
    """
    kind: str
    status: str = "ok"


class Application(BaseModel):
    """
    Application "intent" for the case:
     - type: CEI|CIS|CIP|auto (auto = decide from eligibility)
     - eligibility_reason: EXP_60|AGE_14|CHANGE|LOSS
     - docs: list of Doc
    """
    type: Optional[str] = None
    eligibility_reason: Optional[str] = None
    docs: List[Doc] = []


class ChatIn(BaseModel):
    """
    Chat request payload:
     - session_id: identifies conversation
     - message: user input
     - person/application: optional structured data to skip form-filling
    """
    session_id: str
    message: str
    person: Optional[Person] = None
    application: Optional[Application] = None

# ---- session reset (wipe in-memory chat + FSM state) ----
class ResetIn(BaseModel):
    sid: str


# --------------------------- CHAT ENDPOINT ---------------------------

# --- tiny helpers for toast steps ---
def _toast_ok(title: str, msg: str):
    return {"toast": {"title": title, "msg": msg, "type": "ok"}}

def _toast_info(title: str, msg: str):
    return {"toast": {"title": title, "msg": msg, "type": "info"}}

def _toast_warn(title: str, msg: str):
    return {"toast": {"title": title, "msg": msg, "type": "warn"}}

def _toast_err(title: str, msg: str):
    return {"toast": {"title": title, "msg": msg, "type": "err"}}

async def _recognized_docs_from_ocr(sid: str) -> list[dict]:
    """Query Primărie /local/uploads and turn recognized kinds into doc list."""
    try:
        async with httpx.AsyncClient() as client:
            j = (await client.get(f"{os.getenv('LOCAL_URL','http://127.0.0.1:8000/local')}/uploads",
                                  params={"session_id": sid},
                                  headers={"X-Caller": "orchestrator_recognized_docs_from_ocr"})).json()
        kinds = j.get("recognized", []) or []
        return [{"kind": k, "status": "ok"} for k in kinds]
    except Exception:
        return []


@router.post("/chat")
async def chat_api(data: ChatIn):
    state = {
        "session_id": data.session_id,
        "message": data.message,
        "person": data.person or {},
        "app": data.application or {},
        "steps": [],
    }
    result = await run_agent_graph(state)
    return {
        "reply": result.get("reply", "OK"),
        "steps": result.get("steps", []),
        "halted": True,
    }

# --------------------------- RESCHEDULE / CANCEL ---------------------------
class ReschedIn(BaseModel):
    """
    Payload for rescheduling an existing appointment.
    """
    appt_id: str
    new_slot_id: str


@router.post("/reschedule")
async def reschedule_api(data: ReschedIn):
    """
    Reschedule an appointment at the CEI-HUB (mock).
    """
    return await tool_reschedule(data.appt_id, data.new_slot_id)

@router.post("/session/reset")
def reset_session(data: ResetIn):
    """Drop all state for a given session id."""
    sid = data.sid
    removed = {"sessions": bool(SESSIONS.pop(sid, None)), "state": bool(SESS_STATE.pop(sid, None))}
    return {"ok": True, "removed": removed}

class CancelIn(BaseModel):
    """
    Payload for canceling an appointment.
    """
    appt_id: str


@router.post("/cancel")
async def cancel_api(data: CancelIn):
    """
    Cancel an appointment at the CEI-HUB (mock).
    """
    return await tool_cancel_appointment(data.appt_id)


# --------------------------- RAG SEARCH (DEBUG) ---------------------------

class SearchIn(BaseModel):
    """
    Query for ad-hoc RAG searches (debugging/testing).
    """
    query: str
    k: int = 3


# TODO: should we move this somewhere, because this is generic.What if we have other apps as well, e.g., a "dosar social" in romanian
@router.post("/search")
def rag_search(data: SearchIn):
    """
    Return top-k chunks for a query, with similarity score and source path.
    """
    return rag.search(data.query, data.k)



### -----------------------------------------------------------------
class ValidateIn(BaseModel):
    person: Optional[Person]
    application: Optional[Application]

@router.post("/validate")
def validate_api(data: ValidateIn):
    """
    Validate the user input without creating anything.
    - Decide app type if 'auto'
    - Compute missing docs
    - Return messages the UI can show inline
    """
    app = data.application.model_dump() if data.application else {"type":"auto","eligibility_reason":"EXP_60","docs":[]}
    elig = tool_eligibility(app.get("eligibility_reason","EXP_60"))
    if app.get("type","auto") == "auto":
        app["type"] = elig["decided_type"]


    missing = tool_docs_missing(app["type"], app.get("docs", []))["missing"]
    # Simple person checks (extend as needed)
    errors = []
    pj = data.person.model_dump() if data.person else {}
    if not pj.get("cnp"): errors.append("CNP is required")
    if not pj.get("nume"): errors.append("Last name is required")
    if not pj.get("prenume"): errors.append("First name is required")
    if not pj.get("email"): errors.append("Email is required")

    return {
        "valid": len(errors)==0,
        "errors": errors,
        "decided_type": app["type"],
        "missing": missing
    }

class CreateCaseIn(BaseModel):
    person: Person
    application: Application

@router.post("/create_case")
async def create_case_api(data: CreateCaseIn):
    """
    Create a case only (no auto payment/signature/scheduling).
    Returns the new case_id.
    """
    person = data.person.model_dump()
    app = data.application.model_dump()

    # if user selected “auto”, you decide before this point;
    # here we just enforce that 'type' is actually present ("CEI", "CIS", "CIP")
    if not app.get("type"):
        # fallback to CEI or whatever your decision logic computed earlier
        app["type"] = "CEI"

    app["program"] = app["type"]  # for local case creation

    # Ensure docs completeness client-side first; server still accepts
    case = await tool_case_submit(person, app)
    return case  # { case_id, status }


class CreateCaseSocialIn(BaseModel):
    person: Person
    application: dict  # expects program:"AS", docs:[]

@router.post("/create_case_social")
async def create_case_social(data: CreateCaseSocialIn):
    person = data.person.model_dump()
    app = dict(data.application)

    app["program"] = "AS"

    case = await tool_case_submit(person, app)  # posts to /local/cases
    return case

@router.get("/slots")
async def list_slots_api(location_id: Optional[str] = None):
    """
    Pass-through for hub slots so the form can populate the selector.
    """
    import os, httpx
    HUB_URL = os.getenv("HUB_URL", "http://127.0.0.1:8000/hub")
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{HUB_URL}/slots", params={"location_id": location_id} if location_id else None)
        return r.json()



class ScheduleIn(BaseModel):
    apptype: str
    slot_id: str
    case_id: Optional[str] = None  # kept for auditing/future linking

@router.post("/schedule")
async def schedule_api(data: ScheduleIn):
    """
    Reserve the chosen slot. user explicitly chooses.
    For non-CEI types, we could create a local appointment instead.
    """
    if data.apptype != "CEI":
        return {"via": "LOCAL", "appointment": {"appt_id": "local-na", "when": "soon", "location_id": "Primarie-01"}}
    return await tool_schedule_by_slot(data.slot_id, cnp=None)


@router.get("/slots-social")
async def api_slots_social(location_id: Optional[str] = None):
    LOCAL_URL = os.getenv("LOCAL_URL", "http://127.0.0.1:8000/local")
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{LOCAL_URL}/slots-social", params={"location_id": location_id} if location_id else None)
        return r.json()

@router.post("/schedule-social")
async def api_schedule_social(payload: dict):
    LOCAL_URL = os.getenv("LOCAL_URL", "http://127.0.0.1:8000/local")
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{LOCAL_URL}/reserve-social", json=payload)
        r.raise_for_status()
        return r.json()

