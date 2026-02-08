# Handles scheduling requests by interacting with two different backends
# One agent, two backends (hub vs local) using different endpoints
from __future__ import annotations
import os
import httpx
from agents.http_client import make_async_client
from .base import Agent, AgentState
from .llm_utils import get_domain_from_ui_context
from services.text_chat_messages import translate_msg

HUB_URL = os.getenv("HUB_URL", "http://127.0.0.1:8000/hub")
LOCAL_URL = os.getenv("LOCAL_URL", "http://127.0.0.1:8000/local")


class SchedulingAgent(Agent):
    name = "scheduling"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        ui_context = (app.get("ui_context") or "entry").lower()

        steps = state.setdefault("steps", [])
        steps.append({"type": "open_section", "payload": {"section_id": "slotsBox"}})
        steps.append({"type": "focus_field", "payload": {"field_id": "loc"}})
        steps.append({
            "type": "toast",
            "payload": {
                "level": "info",
                "title": translate_msg(app, "title_scheduling"),
                "message": translate_msg(app, "sched_help")
            }
        })

        # Optional: CEI can hint HubGov refresh (UI may ignore)
        if app.get("type") == "CEI":
            steps.append({
                "type": "hubgov_action",
                "payload": {
                    "action": "hubgov_slots",
                    "args": {"program": app.get("program") or "carte_identitate"}
                }
            })

        state["reply"] = translate_msg(app, "sched_reply")
        state["next_agent"] = get_domain_from_ui_context(ui_context)
        return state
