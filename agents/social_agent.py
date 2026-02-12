# agents/social_agent.py
# Contextual wizard for the Ajutor Social use case, aligned with CI wizard principles.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from services.text_chat_messages import translate_msg
from .base import Agent, AgentState
from .tools import tool_docs_missing
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
                state["reply"] = translate_msg(app, "social_detect_uploads")
                return state

        # Wizard Step 1/3: slot required.
        selected_slot_id = app.get("selected_slot_id") if isinstance(app, dict) else None
        if not selected_slot_id:
            if (not msg) or any(k in msg for k in ["program", "programare", "slot", "ajutor", "social", "vreau"]):
                state["reply"] = translate_msg(app, "social_step1")
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
                state["reply"] = translate_msg(app, "social_step2")
                state["next_agent"] = None
                return state

        # Step 3/3: person fields + docs
        missing_fields = _missing_person_fields(person)
        if missing_fields:
            state.setdefault("steps", []).append({"type":"toast","payload":{"level":"warn","title":"Date lipsa","message": translate_msg(app, "social_missing_fields_toast")}})
            state.setdefault("steps", []).append({"type":"focus_field","payload":{"field_id": missing_fields[0]}})
            state["reply"] = translate_msg(app, "social_step3")
            state["next_agent"] = None
            return state

        required = set(SOCIAL_CFG.get("required_docs") or [])
        docs = app.get("docs") or []
        if not isinstance(docs, list):
            docs = []
        missing_info = tool_docs_missing("as", None, None, docs)
        missing_docs = missing_info.get("missing") or []
        missing_cards = missing_info.get("missing_cards") or []

        if missing_docs:
            state.setdefault("steps", []).append({"type":"highlight_missing_docs","payload":{"kinds": missing_docs}})
            state.setdefault("steps", []).append({"type":"open_section","payload":{"section_id":"slotsBox"}})

            pretty_missing_docs = ", ".join([c.get("label") or c.get("id") for c in missing_cards]) if missing_cards else ", ".join(
                missing_docs)

            state["reply"] = translate_msg(app, "social_missing_docs", docs=pretty_missing_docs)
            state["next_agent"] = None
            return state

        # Ready -> create case.
        state["reply"] = translate_msg(app, "social_ready_create")
        state["next_agent"] = "case"
        return state
