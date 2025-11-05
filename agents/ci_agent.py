
# CI Agent - implements the logic for handling "carte de identitate" applications.
# Uses checklist + existing logic (type, missing docs).
from __future__ import annotations
import json
from pathlib import Path
from .base import Agent, AgentState
from agents.tools import tool_docs_missing, tool_eligibility  # you already have these


CI_CFG = json.loads((Path(__file__).parent / "checklists" / "ci.json").read_text(encoding="utf-8"))


class CIAgent(Agent):
    name = "ci"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        # if we don't have docs yet, try OCR first
        if not app.get("docs"):
            # let the doc-intake agent populate, then come back
            state["next_agent"] = "doc_intake"
            return state

        # eligibility -> decide CEI/CIS/CIP
        elig = tool_eligibility(app.get("eligibility_reason", CI_CFG["eligibility_reason"]))
        if (app.get("type") or "auto") == "auto":
            app["type"] = elig["decided_type"]

        missing = tool_docs_missing(app["type"], app["docs"])["missing"]
        state["app"] = app
        state["steps"] = state.get("steps", [])
        if missing:
            state["steps"].append({"missing": missing})
            state["reply"] = f"Missing documents for {app['type']}: {', '.join(missing)}"
            state["next_agent"] = None
            return state

        # if no missing -> create case
        state["next_agent"] = "case"
        state["reply"] = f"All documents present for {app['type']}. Creating the case…"
        return state
