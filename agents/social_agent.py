# agents/social_agent.py
# Contextual wizard for the Ajutor Social use case.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .base import Agent, AgentState

from db import engine, Upload
from sqlmodel import Session, select


def _get_last_upload_id(sid: str) -> int | None:
    if not sid:
        return None
    with Session(engine) as ss:
        row = ss.exec(select(Upload.id).where(Upload.session_id == sid).order_by(Upload.id.desc())).first()
    return int(row) if row is not None else None


SOCIAL_CFG = json.loads(
    (Path(__file__).parent / "checklists" / "social.json").read_text(encoding="utf-8")
)


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
    if not (person.get("adresa") or "").strip():
        missing.append("adresa")
    return missing


class SocialAgent(Agent):
    name = "social"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        person = state.get("person") or {}
        msg = (state.get("message") or "").lower()
        sid = state.get("session_id") or ""

        if isinstance(app, dict):
            app.setdefault("ui_context", "social")
            app["program"] = "AS"
        state["app"] = app

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
            state["reply"] = "Pentru Ajutor Social am nevoie de datele persoanei. Completeaza campurile marcate cu * si apoi incarcam documentele."
            state["next_agent"] = None
            return state

        # 3) Docs requirements are top-level for this demo.
        required = set(SOCIAL_CFG.get("required_docs") or [])
        docs = app.get("docs") or []
        if not isinstance(docs, list):
            docs = []
        present = {d.get("kind") for d in docs if d.get("status") == "ok"}
        missing_docs = sorted([d for d in required if d not in present])

        if missing_docs:
            state.setdefault("steps", []).append({"missing_docs": missing_docs})
            state["reply"] = "Lipsesc documente: " + ", ".join(missing_docs) + ". Incarca-le in pagina si apoi scrie: am incarcat documentele."
            state["next_agent"] = None
            return state

        # 4) Ready -> create case.
        state["reply"] = "Perfect. Am toate datele si documentele necesare. Creez cererea."
        state["next_agent"] = "case"
        return state
