# Handles scheduling requests by interacting with two different backends
# One agent, two backends (hub vs local) using different endpoints
from __future__ import annotations
import os
import httpx
from agents.http_client import make_async_client
from .base import Agent, AgentState

HUB_URL = os.getenv("HUB_URL", "http://127.0.0.1:8000/hub")
LOCAL_URL = os.getenv("LOCAL_URL", "http://127.0.0.1:8000/local")


class SchedulingAgent(Agent):
    name = "scheduling"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        steps = state.setdefault("steps", [])

        # Show slots
        if app.get("type") == "CEI":
            async with make_async_client() as client:
                slots = (await client.get(f"{HUB_URL}/slots")).json()
            steps.append({"slots": slots})
            state["reply"] = "Here are CEI slots. Say: 'programeaza slot <id>'"
        elif app.get("program") == "AS":
            async with make_async_client() as client:
                slots = (await client.get(f"{LOCAL_URL}/slots-social")).json()
            steps.append({"slots": slots})
            state["reply"] = "Here are local slots for Ajutor social. Say: 'programeaza slot <id>'"
        else:
            state["reply"] = "No scheduling needed."
        state["next_agent"] = None
        return state
