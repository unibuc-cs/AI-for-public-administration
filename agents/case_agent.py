# Calls existing services to create and manage cases, their state, and scheduling.
from __future__ import annotations
import os
import httpx
from .base import Agent, AgentState
from agents.http_client import make_async_client

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

        state.setdefault("steps", []).append({"case_submit": case})
        state["reply"] = f"Case {case['case_id']} created."
        # after case creation you might want scheduling
        if app.get("type") == "CEI" or app.get("program") == "AS":
            state["next_agent"] = "scheduling"
        else:
            state["next_agent"] = None
        return state
