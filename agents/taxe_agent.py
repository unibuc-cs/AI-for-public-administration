# agents/taxe_agent.py
# Minimal scaffold for a 3rd demo use case (Taxe si Impozite).
# Goal: adding new cases should be trivial: checklist JSON + agent class + one router line.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .base import Agent, AgentState
from services.text_chat_messages import translate_msg


TAXE_CFG = json.loads(
    (Path(__file__).parent / "checklists" / "taxe.json").read_text(encoding="utf-8")
)


def _missing_person_fields(person: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    for k in ("cnp", "nume", "prenume", "email", "telefon", "adresa"):
        if not (person.get(k) or "").strip():
            missing.append(k)
    return missing


class TaxeAgent(Agent):
    name = "taxe"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        person = state.get("person") or {}
        msg = (state.get("message") or "").lower()

        if isinstance(app, dict):
            app.setdefault("ui_context", "taxe")
            app["program"] = "TAXE"
        state["app"] = app

        # Step 1: ensure person fields exist (same fields as the other demos for consistency)
        missing_fields = _missing_person_fields(person if isinstance(person, dict) else {})
        if missing_fields:
            state.setdefault("steps", []).append({
                "type": "toast",
                "payload": {
                    "level": "warn",
                    "title": "Date lipsa",
                    "message": "Completeaza campurile necesare in formular.",
                },
            })
            state.setdefault("steps", []).append({"type": "focus_field", "payload": {"field_id": missing_fields[0]}})
            state["reply"] = "Pentru Taxe si Impozite, am nevoie intai de datele tale (CNP, nume, prenume, email, telefon, adresa)."
            state["next_agent"] = None
            return state

        # Step 2: require docs from checklist
        required = set(TAXE_CFG.get("required_docs") or [])
        docs = app.get("docs") or []
        if not isinstance(docs, list):
            docs = []
        present = {d.get("kind") for d in docs if d.get("status") == "ok"}
        missing_docs = sorted([d for d in required if d not in present])
        if missing_docs:
            state.setdefault("steps", []).append({"type": "highlight_missing_docs", "payload": {"kinds": missing_docs}})
            state["reply"] = "Pentru a continua, incarca documentele: " + ", ".join(missing_docs) + "."
            state["next_agent"] = None
            return state

        # Step 3: ready (placeholder)
        state["reply"] = (
            "Am datele si documentele necesare pentru demo TAXE. "
            "Urmatorul pas ar fi: cautare obligatii fiscale / simulare plata / generare dovada. "
            "(Scaffold: completeaza logica in TaxeAgent si un endpoint in primarie_local_mock.)"
        )
        state["next_agent"] = None
        return state
