# agents/doc_ocr_agent.py
# Extract structured fields from uploaded document OCR text and auto-fill form fields.
#
# Notes:
# - This agent reads OCR text stored in the Upload table (no OCR work here).
# - It emits UI steps: {set_fields:{...}} and optionally {focus:"field"}.
# - Policy: always override latest. If a newer upload provides a value, it wins.

from __future__ import annotations

import re
from typing import Any, Dict, List

from sqlmodel import Session, select

from db import engine, Upload
from .base import Agent, AgentState


class DocOCRAgent(Agent):
    name = "doc_ocr"

    def _extract(self, text: str) -> Dict[str, str]:
        """Very small regex extractor. Extend per document type later."""
        t = (text or "")
        out: Dict[str, str] = {}

        # CNP: 13 digits
        m = re.search(r"\b(\d{13})\b", t)
        if m:
            out["cnp"] = m.group(1)

        # Email
        m = re.search(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b", t)
        if m:
            out["email"] = m.group(1)

        # Phone (Romanian style loose)
        m = re.search(r"\b(0\d{9})\b", t)
        if m:
            out["telefon"] = m.group(1)

        # Name-like patterns: "nume: X" / "prenume: Y"
        m = re.search(r"\bnume\s*[:=]\s*([A-Za-z\- ]{2,})", t, flags=re.IGNORECASE)
        if m:
            out["nume"] = m.group(1).strip()
        m = re.search(r"\bprenume\s*[:=]\s*([A-Za-z\- ]{2,})", t, flags=re.IGNORECASE)
        if m:
            out["prenume"] = m.group(1).strip()

        # Address-like pattern: "adresa: ..."
        m = re.search(r"\badresa\s*[:=]\s*(.{6,120})", t, flags=re.IGNORECASE)
        if m:
            out["adresa"] = m.group(1).strip()

        return out

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

        uploads = self._load_uploads(sid)

        # Always override latest: apply in upload order, last match wins.
        extracted: Dict[str, str] = {}
        for u in uploads:
            one = self._extract(u.ocr_text or "")
            for k, v in one.items():
                if v:
                    extracted[k] = v

        set_fields: Dict[str, str] = {}
        for k in ["cnp", "nume", "prenume", "email", "telefon", "adresa"]:
            if extracted.get(k):
                set_fields[k] = extracted[k]

        # Also update server-side state.person so the next agent sees the new values.
        person = state.get("person") or {}
        if not isinstance(person, dict):
            person = {}

        if set_fields:
            for k, v in set_fields.items():
                person[k] = v
            state["person"] = person

            state.setdefault("steps", []).append({"set_fields": set_fields, "source": "doc_ocr"})

            miss = self._first_missing(person)
            if miss:
                state.setdefault("steps", []).append({"focus": miss})

            state["reply"] = "Am completat automat campuri din documentele incarcate. Verifica si corecteaza daca e nevoie."

        state["next_agent"] = state.pop("return_to", None)
        return state
