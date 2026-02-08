# Calls existing services to create and manage cases, their state, and scheduling.
from __future__ import annotations
import os
from .base import Agent, AgentState
from agents.http_client import make_async_client
from services.text_chat_messages import translate_msg

LOCAL_URL = os.getenv("LOCAL_URL", "http://127.0.0.1:8000/local")


class CaseAgent(Agent):
    name = "case"

    async def handle(self, state: AgentState) -> AgentState:
        person = state.get("person") or {}
        app = state.get("app") or {}

        payload = {"person": person, "application": app}

        async with make_async_client() as client:
            r = await client.post(f"{LOCAL_URL}/cases", json=payload)
            case = r.json()

        # typed toast instead of legacy steps
        state.setdefault("steps", []).append({
            "type": "toast",
            "payload": {
                "level": "info",
                "title": translate_msg(app, "title_case"),
                "message": translate_msg(app, "case_created", id=case.get("case_id","?"))
            }
        })
        state["reply"] = translate_msg(app, "case_created", id=case.get("case_id","?"))

        # After case creation you might want scheduling
        if app.get("type") == "CEI" or app.get("program") == "AS":
            state["next_agent"] = "scheduling"
        else:
            state["next_agent"] = None
        return state
