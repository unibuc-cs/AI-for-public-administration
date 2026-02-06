# agents/social_agent.py
# Contextual wizard for the Ajutor Social use case, aligned with CI wizard principles.

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
        row = ss.exec(
            select(Upload.id)
            .where(Upload.session_id == sid)
            .order_by(Upload.id.desc())
        ).first()
    return int(row) if row is not None else None


SOCIAL_CFG = json.loads(
    (Path(__file__).parent / "checklists" / "social.json").read_text(encoding="utf-8")
)


def _missing_person_fields(person: Dict[str, Any]) -> List[str]:
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
        msg_raw = (state.get("message") or "")
        msg = msg_raw.lower()
        sid = state.get("session_id") or ""

        if isinstance(app, dict):
            app.setdefault("ui_context", "social")
            app["program"] = "AS"
        state["app"] = app

        # If user uploaded docs (or uploads changed), automatically run intake+OCR.
        last_id = _get_last_upload_id(sid)
        if last_id is not None:
            seen = app.get("uploads_seen_last_id") if isinstance(app, dict) else None
            if seen != last_id:
                if isinstance(app, dict):
                    app["uploads_seen_last_id"] = last_id
                    state["app"] = app
                state["return_to"] = self.name
                state["next_agent"] = "doc_intake"
                state["reply"] = "Am detectat documente incarcate. Verific si incerc sa completez automat."
                return state

        # Wizard Step 1/3: slot required.
        selected_slot_id = app.get("selected_slot_id") if isinstance(app, dict) else None
        if not selected_slot_id:
            if (not msg) or any(k in msg for k in ["program", "programare", "slot", "ajutor", "social", "vreau"]):
                state["reply"] = (
                    "Step 1/3: Selecteaza un slot in pagina (Slots) si apasa Use this slot. "
                    "Dupa asta continui cu eligibilitate si documente."
                )
                state["next_agent"] = None
                return state

        # Wizard Step 2/3: eligibility + slot (phase2)
        # UI sends __phase2_done__ when slot+elig are selected.
        # For safety, also check app.type_elig_confirmed.
        type_elig_confirmed = bool(app.get("type_elig_confirmed")) if isinstance(app, dict) else False
        if ("__phase2_done__" in msg_raw) or type_elig_confirmed:
            if isinstance(app, dict):
                app["type_elig_confirmed"] = True
                state["app"] = app
        else:
            # If not done, guide.
            elig = (app.get("eligibility_reason") if isinstance(app, dict) else "") or ""
            if not elig or elig == "None":
                state["reply"] = "Step 2/3: Selecteaza eligibilitate (motiv) si apoi pot valida documentele."
                state["next_agent"] = None
                return state

        # Step 3/3: person fields + docs
        missing_fields = _missing_person_fields(person)
        if missing_fields:
            state.setdefault("steps", []).append({"type":"toast","payload":{"level":"warn","title":"Date lipsa","message":"Completeaza campurile lipsa."}})
            state.setdefault("steps", []).append({"type":"focus_field","payload":{"field_id": missing_fields[0]}})
            state["reply"] = "Step 3/3: Completeaza datele persoanei, apoi incarca documentele si apasa Valideaza."
            state["next_agent"] = None
            return state

        required = set(SOCIAL_CFG.get("required_docs") or [])
        docs = app.get("docs") or []
        if not isinstance(docs, list):
            docs = []
        present = {d.get("kind") for d in docs if d.get("status") == "ok"}
        missing_docs = sorted([d for d in required if d not in present])

        if missing_docs:
            state.setdefault("steps", []).append({"type":"highlight_missing_docs","payload":{"kinds": missing_docs}})
            state.setdefault("steps", []).append({"type":"open_section","payload":{"section_id":"slotsBox"}})
            state["reply"] = "Lipsesc documente: " + ", ".join(missing_docs) + ". Incarca-le in pagina."
            state["next_agent"] = None
            return state

        # Ready -> create case.
        state["reply"] = "Perfect. Am toate datele si documentele necesare. Creez cererea."
        state["next_agent"] = "case"
        return state
