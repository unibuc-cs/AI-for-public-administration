# agents/LegalGov.py
# Placeholder agent for legal questions (prototype).

from __future__ import annotations
from .base import Agent, AgentState
from services.text_chat_messages import translate_msg


class LegalGovAgent(Agent):
    name = "legal_gov"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        state["reply"] = translate_msg(app, "legalgov_placeholder")
        state.setdefault("steps", []).append({
            "type": "toast",
            "payload": {
                "level": "info",
                "title": translate_msg(app, "title_legal"),
                "message": translate_msg(app, "legalgov_placeholder"),
            }
        })
        state["next_agent"] = None
        return state
