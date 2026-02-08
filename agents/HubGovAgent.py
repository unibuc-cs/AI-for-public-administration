# agents/HubGovAgent.py
# Placeholder agent for HubGov (CEI hub integration).
# For prototype: only emits a toast + reply, does not call real hub endpoints.

from __future__ import annotations
from .base import Agent, AgentState
from services.text_chat_messages import translate_msg


class HubGovAgent(Agent):
    name = "hubgov"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        steps = state.setdefault("steps", [])
        # If router requested a hubgov_action, keep it but also inform user.
        steps.append({
            "type": "toast",
            "payload": {
                "level": "info",
                "title": translate_msg(app, "title_hubgov"),
                "message": translate_msg(app, "hubgov_placeholder"),
            }
        })
        state["reply"] = translate_msg(app, "hubgov_placeholder")
        state["next_agent"] = None
        return state
