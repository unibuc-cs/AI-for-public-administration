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
# NOTE: The OpenAI model is not directly called here (tool orchestration is
# heuristic). You can swap to LangGraph/LangChain later by wrapping the calls.

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
                                  params={"session_id": sid})).json()
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


    """ TODO: BELOW IS THE OLD CODE. WHat do we do with it? Move to agent graph nodes?
    
    Conversational orchestrator with a tiny per-session state machine.

    Phases:
      - idle        : not started; user can start CI
      - await_docs  : collecting documents; user uploads in /user-ci or says 'am <doc>' here
      - await_slot  : user picks an appointment (we can show slots & accept a slot id)
      - done        : case created & (optionally) scheduled

    The handler also supports 'RAG' questions about required documents.
    """
    sid = data.session_id
    SESSIONS.setdefault(sid, [])
    SESSIONS[sid].append({"role": "user", "content": data.message})
    st = _state(sid)

    text = data.message.strip()
    lower = text.lower()
    link_form = f"/user-ci?sid={sid}"

    # --- 0) RAG shortcut: "what documents / ce acte / ce documente"
    if re.search(r"\b(what documents|ce acte|ce documente)\b", lower):
        hits = rag.search("documente necesare CI")
        answer = "I found:\n" + "\n".join([f"- {h['text'][:200]}… (source: {h['source']})" for h in hits])
        SESSIONS[sid].append({"role": "assistant", "content": answer})
        return {"reply": answer, "steps": [], "halted": True, "citations": hits}

    # --- 1) Start a CI flow intent ---
    if (re.search(r"(carte de identitate|ci nou(a|ă)|create new ci|vreau.*(buletin|ci))", lower)
            and not re.search(r"social", lower)):
        st["phase"] = "await_docs"
        # reset app minimal if user passed payload we respect it
        st["person"] = data.person.model_dump() if data.person else st["person"]
        st["app"] = data.application.model_dump() if data.application else st["app"]
        msg = (
            f"Great — let’s start your CI request. Please complete & upload here: {link_form}\n"
            f"Tip: after you upload, say **gata** here (or press Validate in the form)."
        )
        SESSIONS[sid].append({"role": "assistant", "content": msg})
        return {
            "reply": msg,
            "steps": [
                _toast_info("Formular CI", "Deschide formularul și încarcă documentele.")
            ],
            "halted": True
        }

    # --- 1.b) Start Ajutor social flow ---
    if re.search(r"\b(ajutor social|venit de incluziune|vi)\b", lower):
        st["phase"] = "await_docs"
        # Mark app as AS program, keep person if provided
        st["person"] = data.person.model_dump() if data.person else st["person"]
        st["app"] = {"program": "AS", "docs": []}
        msg = (
            "Începem cererea pentru Ajutor social. Te rog completează și încarcă aici: "
            f"/user-social?sid={sid}\nDupă ce termini, spune **gata** sau apasă Validează în formular."
        )
        SESSIONS[sid].append({"role": "assistant", "content": msg})
        return {"reply": msg, "steps": [], "halted": True}

    # --- 2) If user mentions a document in chat, DO NOT mark it here.
    #       We enforce "OCR-only" verification: user must upload, OCR decides.
    if st["phase"] in {"await_docs", "idle"}:
        for pattern, kind in _doc_synonyms().items():
            if re.search(pattern, lower):
                reply = (
                    f"Am înțeles «{kind}». Te rog încarcă documentul în formular: {link_form}. "
                    f"După upload, îl verific prin OCR și bifez automat."
                )
                return {"reply": reply, "steps": [_toast_info("Upload necesar", kind)], "halted": True}

    # --- 3) User says they finished uploads / provided structured data from form ---
    if re.search(r"\b(gata|am incarcat|am încărcat|ready|validate)\b", lower) or (data.application is not None):
        # pull the latest structured payload if provided
        if data.person:
            st["person"] = data.person.model_dump()

        if data.application:
            st["app"] = data.application.model_dump()

        # If no docs were provided via the form, pull them from OCR uploads (truth source)
        if not st["app"].get("docs"):
            docs_from_ocr = await _recognized_docs_from_ocr(sid)
            if docs_from_ocr:
                st["app"]["docs"] = docs_from_ocr
                print(f"[{sid}] OCR docs pulled: {[d['kind'] for d in docs_from_ocr]}")

        # decide type & compute missing
        if st["app"].get("program") != "AS":
            elig = tool_eligibility(st["app"].get("eligibility_reason", "EXP_60"))
            if (st["app"].get("type") or "auto") == "auto":
                st["app"]["type"] = elig["decided_type"]
        else:
            elig = {"decided_type": "AS", "reason": None}

        missing = tool_docs_missing(st["app"]["type"], st["app"].get("docs", []))["missing"]
        st["missing"] = missing
        st["decided_type"] = st["app"]["type"]

        if missing:
            msg = f"I recommend **{st['app']['type']}**. Still missing: {', '.join(missing)}. Upload here: {link_form}"
            SESSIONS[sid].append({"role": "assistant", "content": msg})
            return {
                "reply": msg,
                "steps": [{"eligibility": elig}, {"missing": missing},
                          _toast_warn("Documente lipsă", ", ".join(missing))],
                "halted": True
            }

        # No missing docs — next step depends on type
        if st["app"]["type"] == "CEI":
            st["phase"] = "await_slot"
            msg = (
                "Perfect, documents are complete. Please **choose a slot** in the form "
                f"or say **arată sloturi** and then **programează slot <id>**. Form: {link_form}"
            )
            SESSIONS[sid].append({"role": "assistant", "content": msg})
            return {
                "reply": msg,
                "steps": [{"eligibility": elig}, {"missing": []}, _toast_ok("Validare", "Complete. Alege un slot.")],
                "halted": True
            }
        else:
            msg = "Documents complete ✅. Say **creează dosarul** and I’ll create the case."
            SESSIONS[sid].append({"role": "assistant", "content": msg})
            return {
                "reply": msg,
                "steps": [{"eligibility": elig}, {"missing": []}, _toast_info("Validare", "Spune «creează dosarul».")],
                "halted": True
            }

    # --- 4) Show slots on demand (CEI only) ---
    if re.search(r"(arata sloturi|arată sloturi|show slots)", lower):
        if st["app"].get("type") != "CEI":
            reply = "Slots are only needed for CEI. For CIS/CIP we’ll schedule locally when we create the case."
            SESSIONS[sid].append({"role": "assistant", "content": reply})
            return {"reply": reply, "steps": [], "halted": True}
        # fetch from HUB
        HUB_URL = os.getenv("HUB_URL", "http://127.0.0.1:8000/hub")
        async with httpx.AsyncClient() as client:
            slots = (await client.get(f"{HUB_URL}/slots")).json()
        top = slots[:8]
        lines = [f"- {s['id']} : {s['when']} @ {s['location_id']}" for s in top]
        reply = "Here are a few available slots (id : when @ location):\n" + "\n".join(lines) + \
                "\nSay: **programează slot <id>**"
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        st["phase"] = "await_slot"
        return {
            "reply": reply,
            "steps": [{"slots": top}, _toast_info("Sloturi", f"{len(top)} sugestii afișate")],
            "halted": True
        }

    # --- 5) Schedule by slot id ---
    m = re.search(r"(programeaza|programează|schedule)\s+slot\s+([A-Za-z0-9._\-:T]+)", lower)
    if m:
        slot_id = m.group(2)
        cnp = st.get("person", {}).get("cnp")

        # Decide channel: CEI via HUB, AS via LOCAL, else fallback LOCAL placeholder
        if st["app"].get("type") == "CEI":
            sch = await tool_schedule_by_slot(slot_id, cnp=cnp)
        elif st["app"].get("program") == "AS":
            sch = await tool_schedule_social_by_slot(slot_id, cnp=cnp)
        else:
            sch = {"via": "LOCAL", "appointment": {"appt_id": "local-na", "when": "soon", "location_id": "Primarie-01"}}

        st["phase"] = "done"
        reply = f"Programat ✅: {sch.get('appointment', {}).get('when', '')} (id={slot_id})."
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [{"scheduling": sch}, _toast_ok("Programat", slot_id)], "halted": False}

    # --- 6) Create case on demand (works for CI and AS) ---
    if re.search(r"(creeaz(a|ă) dosarul|creeaza dosarul|create case)", lower):
        if st["missing"]:
            msg = f"Încă lipsesc: {', '.join(st['missing'])}. Încarcă aici: /user-ci?sid={sid}"
            if st["app"].get("program") == "AS":
                msg = f"Încă lipsesc: {', '.join(st['missing'])}. Încarcă aici: /user-social?sid={sid}"
            SESSIONS[sid].append({"role": "assistant", "content": msg})
            return {"reply": msg, "steps": [{"missing": st["missing"]}], "halted": True}

        # Build an 'application' dict compatible with Primărie API
        app_payload = {}
        if st["app"].get("program") == "AS":
            app_payload["program"] = "AS"
            app_payload["docs"] = st["app"].get("docs", [])
        else:
            # CI branch
            app_payload["type"] = st["app"].get("type") or "CEI"
            app_payload["eligibility_reason"] = st["app"].get("eligibility_reason")
            app_payload["docs"] = st["app"].get("docs", [])

        case = await tool_case_submit(st["person"], app_payload)
        steps = [{"case_submit": case}]

        # Payment/signature for CI only (and only if endpoints exist)
        pay_res = sig_res = None
        if app_payload.get("type") in {"CEI", "CIS"}:
            fee = 40 if app_payload["type"] == "CIS" else 0
            if fee > 0:
                pay_res = await tool_payment(case["case_id"], fee)
            sig_res = await tool_signature(case["case_id"])
            steps.append({"payment": pay_res or {"skipped": True}})
            steps.append({"signature": sig_res or {"skipped": True}})

        # Scheduling:
        #  - CEI → user chooses slot (keep phase=await_slot if not yet scheduled)
        #  - AS  → local reserve by explicit slot command, or via the AS form button
        if app_payload.get("type") == "CEI":
            st["phase"] = "await_slot"
            reply = (
                f"Dosarul {case['case_id']} a fost creat ✅. Alege o programare: spune **arată sloturi** "
                f"sau selectează în formular: /user-ci?sid={sid}"
            )
            steps.append(_toast_ok("Dosar creat", case["case_id"]))
            SESSIONS[sid].append({"role": "assistant", "content": reply})
            return {"reply": reply, "steps": steps, "halted": True}

        if app_payload.get("program") == "AS":
            # no auto-reserve; user can: 'programează slot <id>' in chat or button in /user-social
            st["phase"] = "await_slot"
            reply = (
                f"Dosarul {case['case_id']} (Ajutor social) a fost creat ✅. "
                f"Alege un slot în formular /user-social?sid={sid} sau spune **programează slot &lt;id&gt;**."
            )
            steps.append(_toast_ok("Dosar creat", case["case_id"]))
            SESSIONS[sid].append({"role": "assistant", "content": reply})
            return {"reply": reply, "steps": steps, "halted": True}

        # fallback
        st["phase"] = "done"
        reply = f"Dosarul {case['case_id']} a fost creat ✅."
        steps.append(_toast_ok("Dosar creat", case["case_id"]))
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": steps, "halted": False}

    # -------------------- OPERATOR INTENTS --------------------
    # These work best when the Operator chat widget uses sid like: op-<username>
    # Supports chat control of cases, tasks, and appointments.
    # Stores per-operator memory: last_case_id / last_appt_id
    # Examples:
    #  - "list tasks" / "list tasks open"
    #  - "claim task 12"
    #  - "done task 12 notes: applicant confirmed new address"
    #  - "advance case CASE-123 to READY_FOR_PICKUP"
    #  - "list cases"
    #  - "reschedule appt APPT-abc to slot 2025-10-20T09:00Z-Bucuresti-S1"
    #  - "cancel appt APPT-abc"

    LOCAL_URL = os.getenv("LOCAL_URL", "http://127.0.0.1:8000/local")

    # helper to infer operator email from sid (op-alex -> alex@demo.local)
    def _assignee_from_sid() -> str:
        if sid.startswith("op-") and len(sid) > 3:
            return f"{sid[3:]}@demo.local"
        return "operator@demo.local"

    # ensure operator memory exists
    mem = _state(sid).setdefault("memory", {"last_case_id": None, "last_appt_id": None})

    # --- list tasks
    m = re.search(r"\b(list|show)\s+tasks(?:\s+(open|assigned|done))?(?:\s+(as|cei|cis|cip))?\b", lower)
    if m:
        status = m.group(2)
        ttype = m.group(3)
        params = {}
        if status: params["status"] = status.upper()
        if ttype:
            map_t = {"as": "AS", "cei": "CEI", "cis": "CIS", "cip": "CIP"}
            params["type"] = map_t.get(ttype, ttype.upper())
        async with httpx.AsyncClient() as client:
            tasks = (await client.get(f"{LOCAL_URL}/tasks", params=params or None)).json()

        if not tasks:
            reply = "No tasks."
        else:
            lines = [
                f"- #{t['id']} [{t['status']}] {t['kind']} (case={t['case_id']}, type={t.get('case_type') or '-'}) "
                f"assignee={t.get('assignee') or '-'}"
                for t in tasks[:12]]

            more = "" if len(tasks) <= 12 else f"\n… and {len(tasks) - 12} more"
            reply = "Tasks:\n" + "\n".join(lines) + more
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [{"tasks": tasks}], "halted": True}

    # --- claim task <id>
    m = re.search(r"\b(claim|preia)\s+task\s+(\d+)\b", lower)
    if m:
        task_id = int(m.group(2))
        assignee = _assignee_from_sid()
        async with httpx.AsyncClient() as client:
            res = (await client.post(f"{LOCAL_URL}/tasks/{task_id}/claim", json={"assignee": assignee})).json()
        reply = f"Task #{task_id} claimed by {assignee} ✅."
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [{"claim": res}], "halted": True}

    # --- done task <id> [notes: ...]
    m = re.search(r"\b(done|complete|finalizeaz(a|ă))\s+task\s+(\d+)(?:\s+notes:\s*(.+))?$", lower)
    if m:
        task_id = int(m.group(3))
        notes = m.group(4) or ""
        async with httpx.AsyncClient() as client:
            res = (await client.post(f"{LOCAL_URL}/tasks/{task_id}/complete", json={"notes": notes})).json()
        reply = f"Task #{task_id} marked DONE ✅." + (f" Notes: {notes}" if notes else "")
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [{"done": res}], "halted": True}

    # --- list cases (reads 'type', 'person', 'application' from service)
    if re.search(r"\b(list|show)\s+cases\b", lower):
        async with httpx.AsyncClient() as client:
            cases = (await client.get(f"{LOCAL_URL}/cases")).json()
        if not cases:
            reply = "No cases."
        else:
            lines = [
                f"- {c['case_id']} [{c['status']}] type={c.get('type')} "
                f"{(c.get('person') or {}).get('nume', '')} {(c.get('person') or {}).get('prenume', '')}"
                for c in cases[:12]
            ]
            more = "" if len(cases) <= 12 else f"\n… and {len(cases) - 12} more"
            reply = "Cases:\n" + "\n".join(lines) + more
        return {"reply": reply, "steps": [{"cases": cases}, _toast_info("Dosare", f"{len(cases)} rezultate")],
                "halted": True}

    # --- advance case <id> to <STATUS>
    m = re.search(r"\b(advance|set|schimb(a|ă))\s+case\s+([A-Za-z0-9\-]+)\s+(?:to|la)\s+([A-Z_]+)\b", lower)
    if m:
        case_id = m.group(3)
        next_status = m.group(4)
        async with httpx.AsyncClient() as client:
            res = (await client.patch(f"{LOCAL_URL}/cases/{case_id}", params={"status": next_status})).json()
        mem["last_case_id"] = case_id
        reply = f"Case {case_id} advanced to {next_status} ✅."
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [{"advance": res}], "halted": True}

    # --- reschedule appt <id> to slot <slot_id>
    m = re.search(
        r"\b(reschedule|reprogrameaz(a|ă))\s+(?:appt|appointment)\s+([A-Za-z0-9._\-]+)\s+(?:to|la)\s+slot\s+([^\s]+)",
        lower)
    if m:
        appt_id = m.group(3)
        slot_id = m.group(4)
        res = await tool_reschedule(appt_id, slot_id)
        mem["last_appt_id"] = appt_id
        reply = f"Appointment {appt_id} rescheduled to slot {slot_id} ✅."
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [{"reschedule": res}], "halted": True}

    # --- shorthand: "reschedule to slot X" (use last_appt_id)
    m = re.search(r"\b(reschedule|reprogrameaz(a|ă))\s+(?:to|la)\s+slot\s+([^\s]+)", lower)
    if m and mem.get("last_appt_id"):
        appt_id = mem["last_appt_id"]
        slot_id = m.group(3)
        res = await tool_reschedule(appt_id, slot_id)
        reply = f"Appointment {appt_id} rescheduled to slot {slot_id} ✅ (remembered last appt)."
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [{"reschedule": res}], "halted": True}

    # --- cancel appt <id>
    m = re.search(r"\b(cancel|anuleaz(a|ă))\s+(?:appt|appointment)\s+([A-Za-z0-9._\-]+)\b", lower)
    if m:
        appt_id = m.group(3)
        res = await tool_cancel_appointment(appt_id)
        mem["last_appt_id"] = appt_id
        reply = f"Appointment {appt_id} canceled ✅."
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [{"cancel": res}], "halted": True}

    # --- shorthand: "cancel appointment" (no id -> reuse memory)
    if re.search(r"\b(cancel|anuleaz(a|ă))\s+(?:appt|appointment)\b", lower) and mem.get("last_appt_id"):
        appt_id = mem["last_appt_id"]
        res = await tool_cancel_appointment(appt_id)
        reply = f"Appointment {appt_id} canceled ✅ (remembered last appt)."
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [{"cancel": res}], "halted": True}

    if re.search(r"\b(forget|clear memory|reset)\b", lower):
        mem.update({"last_case_id": None, "last_appt_id": None})
        reply = "Operator memory cleared."
        SESSIONS[sid].append({"role": "assistant", "content": reply})
        return {"reply": reply, "steps": [], "halted": True}

    # --- 7) Default guidance ---
    # -------------------- DEFAULT HELP --------------------
    if sid.startswith("op-"):
        help_msg = (
            "Sunt asistentul pentru operator. Comenzi utile:\n"
            "• „list tasks”, „list tasks open”\n"
            "• „claim task 12”, „done task 12 notes: ...”\n"
            "• „list cases”, „advance case CASE-123 la READY_FOR_PICKUP”\n"
            "• „reschedule appt APPT-1 la slot <id>”, „cancel appt APPT-1”\n"
            "• „forget” (șterge contextul operatorului)"
        )
    else:
        help_msg = (
            "Te pot ajuta cu CI și Ajutor social. Încearcă:\n"
            "• „Vreau să-mi fac o carte de identitate nouă.”\n"
            "• „Ajutor social” / „venit de incluziune”\n"
            "• „Ce documente sunt necesare?”\n"
            "• „Gata” (după upload)\n"
            "• „Arată sloturi” / „Programează slot <id>”\n"
            "• „Creează dosarul”"
        )

    SESSIONS[sid].append({"role": "assistant", "content": help_msg})
    return {"reply": help_msg, "steps": [], "halted": True}

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

