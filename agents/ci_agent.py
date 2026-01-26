# agents/ci_agent.py
# Contextual wizard for the CI use case.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .base import Agent, AgentState
from .tools import tool_docs_missing, tool_eligibility



from db import engine, Upload
from sqlmodel import Session, select


def _get_last_upload_id(sid: str) -> int | None:
    if not sid:
        return None
    with Session(engine) as ss:
        row = ss.exec(select(Upload.id).where(Upload.session_id == sid).order_by(Upload.id.desc())).first()
    return int(row) if row is not None else None

CI_CFG = json.loads((Path(__file__).parent / "checklists" / "ci.json").read_text(encoding="utf-8"))


def _missing_person_fields(person: Dict[str, Any]) -> List[str]:
    # UI input ids: cnp, nume, prenume, email, telefon, adresa
    missing: List[str] = []
    if not (person.get("cnp") or "").strip():
        missing.append("cnp")
    if not (person.get("nume") or "").strip():
        missing.append("nume")
    if not (person.get("prenume") or "").strip():
        missing.append("prenume")
    if not (person.get("email") or "").strip():
        missing.append("email")
    if not (person.get("telefon") or "").strip():
        missing.append("telefon")
    # Keep address flat for the demo UI
    if not (person.get("adresa") or "").strip():
        missing.append("adresa")
    return missing


class CIAgent(Agent):
    name = "ci"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        person = state.get("person") or {}
        msg = (state.get("message") or "").lower()
        sid = state.get("session_id") or ""

        # Make sure context is pinned when we are inside the CI form.
        if isinstance(app, dict):
            app.setdefault("ui_context", "ci")

        # Auto-run intake+OCR when uploads changed (no need for user to type anything).
        last_id = _get_last_upload_id(sid)
        if last_id is not None:
            seen = app.get("uploads_seen_last_id")
            if seen != last_id:
                app["uploads_seen_last_id"] = last_id
                state["app"] = app
                state["return_to"] = self.name
                state["next_agent"] = "doc_intake"
                state["reply"] = "Am detectat documente incarcate. Verific si incerc sa completez automat."
                return state


        # Slot guidance (form-first UX):
        # On the CI form, the user must pick a slot in the UI selector to unlock the form.
        # We keep this simple: if no slot is selected yet, the assistant nudges the user to do so.
        if isinstance(app, dict):
            selected_slot_id = app.get("selected_slot_id")
        else:
            selected_slot_id = None

        if not selected_slot_id:
            # Only nudge when user is asking about scheduling or starting the flow.
            if (not msg) or any(k in msg for k in ["program", "programare", "slot", "programeaza", "vreau", "ajuta"]):
                state["reply"] = (
                    "Pentru CI, te rog mai întâi să alegi un interval din lista **Slots** (sus), apoi apasă **Use this slot**. "
                    "După aceea pot verifica actele și te ghidez mai departe."
                )
                state["next_agent"] = None
                return state

        # 1) If user indicates they uploaded docs, run intake+OCR.
        if any(k in msg for k in ["am incarcat", "am upload", "incarcat", "upload"]):
            state["return_to"] = self.name
            # Prevent re-triggering the auto-intake loop within the same request.
            last_id = _get_last_upload_id(sid)
            if last_id is not None and isinstance(app, dict):
                app["uploads_seen_last_id"] = last_id
                state["app"] = app
            state["next_agent"] = "doc_intake"
            state["reply"] = "Ok. Verific documentele incarcate si incerc sa completez automat ce pot."
            return state

        # 2) Require basic person fields.
        missing_fields = _missing_person_fields(person)
        if missing_fields:
            state.setdefault("steps", []).append({
                "missing_fields": missing_fields,
                "focus": missing_fields[0],
            })
            state["reply"] = "Pentru CI am nevoie de datele persoanei. Completeaza campurile marcate cu * (minim CNP, nume, prenume, email, telefon, adresa)."
            state["next_agent"] = None
            return state

        # 3) Decide application type (auto) from eligibility.
        elig_reason = (app.get("eligibility_reason") or CI_CFG.get("eligibility_reason") or "EXP_60")
        elig = tool_eligibility(elig_reason)
        if (app.get("type") or "auto") == "auto":
            app["type"] = elig["decided_type"]
        state.setdefault("steps", []).append({"eligibility": elig, "type": app.get("type")})

        # 4) If no docs yet, ask user to upload (or say "am incarcat").
        docs = app.get("docs") or []
        if not isinstance(docs, list):
            docs = []
        app["docs"] = docs
        state["app"] = app

        missing_docs = tool_docs_missing(app["type"], docs)["missing"]
        if missing_docs:
            state.setdefault("steps", []).append({"missing_docs": missing_docs})
            state["reply"] = "Lipsesc documente: " + ", ".join(missing_docs) + ". Incarca-le in pagina si apoi scrie: am incarcat documentele."
            state["next_agent"] = None
            return state

        # 5) Ready -> create case.
        state["reply"] = "Perfect. Am toate datele si documentele necesare. Creez cererea."
        state["next_agent"] = "case"
        return state
