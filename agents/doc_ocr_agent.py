# agents/doc_ocr_agent.py
# Extract structured fields from uploaded document OCR text and auto-fill form fields.
#
# Notes:
# - This agent reads OCR text stored in the Upload table (no OCR work here).
# - It emits UI steps: {set_fields:{...}} and optionally {focus:"field"}.
# - Policy: always override latest. If a newer upload provides a value, it wins.

from __future__ import annotations

from typing import Any, Dict, List

from sqlmodel import Session, select

from db import engine, Upload
from .base import Agent, AgentState
from services.ocr_utils import extract_person_fields


class DocOCRAgent(Agent):
    name = "doc_ocr"

    def _extract(self, text: str) -> Dict[str, str]:
        """Best-effort extraction for demo OCR text."""
        return extract_person_fields(text or "")

    def _load_uploads(self, sid: str) -> List[Upload]:
        with Session(engine) as ss:
            return ss.exec(
                select(Upload).where(Upload.session_id == sid).order_by(Upload.id)
            ).all()

    @staticmethod
    def _first_missing(person: Dict[str, Any]) -> str | None:
        order = ["cnp", "nume", "prenume", "email", "telefon", "adresa"]
        for k in order:
            if not (str(person.get(k) or "").strip()):
                return k
        return None

    async def handle(self, state: AgentState) -> AgentState:
        sid = state.get("session_id") or ""
        if not sid:
            state["next_agent"] = state.pop("return_to", None)
            return state

        # Load all uploads for this session (from DB)
        uploads = self._load_uploads(sid)

        # Always override latest: apply in upload order, last match wins.
        extracted: Dict[str, str] = {}
        for u in uploads:
            one = self._extract(u.ocr_text or "")
            for k, v in one.items():
                if v:
                    extracted[k] = v

        # Prepare set_fields for the form
        set_fields: Dict[str, str] = {}
        for k in ["cnp", "nume", "prenume", "email", "telefon", "adresa"]:
            if extracted.get(k):
                set_fields[k] = extracted[k]

        app = state.get("app") or {}
        if set_fields:
            if not isinstance(app, dict):
                app = {}

            # Store the pending fields recognized from OCR such that the UI can render them later
            app["pending_autofill_fields"] = set_fields
            state["app"] = app

            # Friendly preview (ASCII)
            lines = []
            for k, label in [("prenume", "Prenume"), ("nume", "Nume"), ("cnp", "CNP"), ("adresa", "Adresa"),
                             ("email", "Email"), ("telefon", "Telefon")]:
                if set_fields.get(k):
                    lines.append(f"{label}: {set_fields[k]}")

            # Prompt user to confirm auto-fill
            state["reply"] = (
                    "I found these fields from OCR:\n" + "\n".join(lines) +
                    "\n\nDo you want me to fill them in the form? (da/nu)"
            )
        else:
            app = state.get("app") or {}
            if not isinstance(app, dict):
                app = {}
            app["pending_autofill_fields"] = {}
            state["app"] = app
            state["reply"] = "I could not extract usable fields from OCR. You can fill manually."

        # Return to the previous agent set in the flow
        state["next_agent"] = state.pop("return_to", None)
        return state
