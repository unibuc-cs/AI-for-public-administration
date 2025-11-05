# Handles the "operator" agent mode by interacting with a local service to list tasks and cases.
# Wrap existing commands like "list tasks" and "list cases", claim, done, etc.


# TODO: MOVE THE LOGIC FROM orchestrator.py INTO THIS AGENT CLASS !!!!!!!!!!!!!!!!!!!!!!!!!!!!

from __future__ import annotations
import os
import httpx
from .base import Agent, AgentState

LOCAL_URL = os.getenv("LOCAL_URL", "http://127.0.0.1:8000/local")


class OperatorAgent(Agent):
    name = "operator"

    async def handle(self, state: AgentState) -> AgentState:
        text = state.get("message", "").lower()

        async with httpx.AsyncClient() as client:
            if "list tasks" in text:
                tasks = (await client.get(f"{LOCAL_URL}/tasks")).json()
                state.setdefault("steps", []).append({"tasks": tasks})
                state["reply"] = f"Found {len(tasks)} tasks."
                return state

            if "list cases" in text:
                cases = (await client.get(f"{LOCAL_URL}/cases")).json()
                state.setdefault("steps", []).append({"cases": cases})
                state["reply"] = f"Found {len(cases)} cases."
                return state

        state["reply"] = "Operator mode: try 'list tasks' or 'list cases'."
        state["next_agent"] = None
        return state
