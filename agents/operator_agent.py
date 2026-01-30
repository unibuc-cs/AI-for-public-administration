# agents/operator_agent.py
# Operator backoffice agent: list tasks/cases and perform simple actions.
# When LLM_USE=1, commands are parsed with an LLM and then validated against allowlists.
# Otherwise, we fall back to rule-based parsing.

from __future__ import annotations
import os
import re
import httpx
from typing import Any, Dict, Optional

from .base import Agent, AgentState
from .settings import LLM_USE
from .identifiers import allowed_operator_actions, allowed_case_statuses
from .llm_utils import parse_operator_command_with_llm
from agents.http_client import make_async_client

_ACTIONS = allowed_operator_actions()
_CASE_STATUSES = allowed_case_statuses()

def _normalize_status(s: str) -> Optional[str]:
    if not isinstance(s, str):
        return None
    t = s.strip().upper().replace(" ", "_")
    if re.fullmatch(r"[A-Z0-9_]{2,40}", t):
        return t
    return None

def _fallback_parse(text: str) -> Dict[str, Any]:
    t = (text or "").lower()

    if "list tasks" in t or "listeaza task" in t or "taskuri" in t:
        return {"action": "list_tasks", "confidence": 0.7}
    if "list cases" in t or "listeaza caz" in t or "dosare" in t or "cazuri" in t:
        return {"action": "list_cases", "confidence": 0.7}

    m = re.search(r"(claim|ia|preia)\s+task\s+(\d+)", t)
    if m:
        return {"action": "claim_task", "task_id": int(m.group(2)), "confidence": 0.7}

    m = re.search(r"(complete|done|inchide|finalizeaza)\s+task\s+(\d+)", t)
    if m:
        return {"action": "complete_task", "task_id": int(m.group(2)), "confidence": 0.7}

    m = re.search(r"(advance|trece|muta)\s+case\s+([A-Za-z0-9\-]+)\s+(?:to|la)\s+([A-Za-z0-9_\- ]+)", t)
    if m:
        return {"action": "advance_case", "case_id": m.group(2), "status": m.group(3), "confidence": 0.6}

    return {"action": "unknown", "confidence": 0.2}

class OperatorAgent(Agent):
    name = "operator"

    async def handle(self, state: AgentState) -> AgentState:
        text = state.get("message", "") or ""
        from .tools import LOCAL_URL  # consistent RUN_MODE defaults

        # 1) LLM parse (optional)
        cmd: Dict[str, Any] = {}
        if LLM_USE:
            try:
                cmd = await parse_operator_command_with_llm(text, allowed_statuses=sorted(_CASE_STATUSES))
            except Exception:
                cmd = {}

        # 2) Validate / sanitize the parsed output (or fallback)
        if not isinstance(cmd, dict) or not cmd:
            cmd = _fallback_parse(text)

        action = (cmd.get("action") or "unknown").strip().lower()
        if action not in _ACTIONS:
            action = "unknown"

        task_id = cmd.get("task_id")
        if task_id is not None:
            try:
                task_id = int(task_id)
            except Exception:
                task_id = None
        if task_id is not None and task_id <= 0:
            task_id = None

        case_id = cmd.get("case_id")
        if case_id is not None and not isinstance(case_id, str):
            case_id = None
        if isinstance(case_id, str):
            case_id = case_id.strip()

        status = _normalize_status(cmd.get("status") or "") if cmd.get("status") is not None else None
        if status is not None and status not in _CASE_STATUSES:
            status = None
        if status is not None and status not in _CASE_STATUSES:
            # If the LLM returns something outside the allowlist, treat it as invalid.
            status = None

        # 3) Execute
        async with make_async_client() as client:
            if action == "list_tasks":
                tasks = (await client.get(f"{LOCAL_URL}/tasks")).json()
                state.setdefault("steps", []).append({"tasks": tasks})
                state["reply"] = f"Found {len(tasks.get('tasks', tasks))} tasks."
                state["next_agent"] = None
                return state

            if action == "list_cases":
                cases = (await client.get(f"{LOCAL_URL}/cases")).json()
                state.setdefault("steps", []).append({"cases": cases})
                state["reply"] = f"Found {len(cases.get('cases', cases))} cases."
                state["next_agent"] = None
                return state

            if action == "claim_task" and task_id is not None:
                r = await client.post(f"{LOCAL_URL}/tasks/{task_id}/claim")
                r.raise_for_status()
                payload = r.json()
                state.setdefault("steps", []).append({"claim": payload})
                state["reply"] = f"Task {task_id} claimed."
                state["next_agent"] = None
                return state

            if action == "complete_task" and task_id is not None:
                r = await client.post(f"{LOCAL_URL}/tasks/{task_id}/complete", json={"notes": ""})
                r.raise_for_status()
                payload = r.json()
                state.setdefault("steps", []).append({"complete": payload})
                state["reply"] = f"Task {task_id} completed."
                state["next_agent"] = None
                return state

            if action == "advance_case" and case_id and status:
                r = await client.patch(f"{LOCAL_URL}/cases/{case_id}", params={"status": status})
                r.raise_for_status()
                payload = r.json()
                state.setdefault("steps", []).append({"advance": payload})
                state["reply"] = f"Case {case_id} updated to {status}."
                state["next_agent"] = None
                return state

        state["reply"] = (
            "Comenzi suportate: list tasks, list cases, claim task <id>, complete task <id>, "
            "advance case <CASE-ID> to <STATUS>. "
            f"STATUS  {sorted(_CASE_STATUSES)}."
        )
        state["next_agent"] = None
        return state
