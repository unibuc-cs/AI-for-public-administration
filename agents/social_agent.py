# agents/social_agent.py
from __future__ import annotations
import json
from pathlib import Path
from .base import Agent, AgentState

SOCIAL_CFG = json.loads((Path(__file__).parent / "checklists" / "social.json").read_text(encoding="utf-8"))


class SocialAgent(Agent):
    name = "social"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        app["program"] = "AS"
        state["app"] = app

        # if no docs, let doc-intake run
        if not app.get("docs"):
            state["return_to"] = self.name
            state["next_agent"] = "doc_intake"
            return state

        # check missing docs
        required = set(SOCIAL_CFG["required_docs"])
        present = {d["kind"] for d in app["docs"]}
        missing = list(required - present)

        state.setdefault("steps", [])
        if missing:
            state["steps"].append({"missing": missing})
            state["reply"] = f"Missing documents for Ajutor social: {', '.join(missing)}"
            state["next_agent"] = None
            return state

        # ready -> create case
        state["next_agent"] = "case"
        state["reply"] = "Documents complete for Ajutor social. Creating the case…"
        return state
