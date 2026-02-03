# agents/router_v2_agent.py
from __future__ import annotations
from typing import Any, Dict
from .base import Agent, AgentState
from .settings import LLM_USE
from .llm_utils import route_with_llm, _ALLOWED_INTENTS, _ALLOWED_ACTIONS
from .entry_agent import _intent_from_text_fallback  # reuse fallback


class RouterAgent(Agent):
    name = "routerAgent"

    async def handle(self, state: AgentState) -> AgentState:
        text = (state.get("message") or "").strip()
        app = state.get("app") or {}
        ui_context = (app.get("ui_context") or "public").lower() if isinstance(app, dict) else "public"

        if not text:
            state["next_agent"] = "entry"  # safe default
            return state

        out: Dict[str, Any] = {}
        if LLM_USE:
            try:
                history = state.get("history") or []

                # ensure the current message is present as last user turn
                # (orchestrator already adds it, but keep safe)
                if not history or history[-1].get("role") != "user":
                    history = history + [{"role":"user","content": text}]

                # Send last turns to LLM for routing
                out = await route_with_llm(history[-20:])
            except Exception:
                out = {}

        # Get predicted intent/action/confidence
        intent = (out.get("intent") or "").strip().lower()
        action = (out.get("action") or "").strip().lower()
        conf = float(out.get("confidence") or 0.0)

        # If not confident, or not valid, fallback to the EntryAgent logic
        if intent not in _ALLOWED_INTENTS or action not in _ALLOWED_ACTIONS or conf < 0.55:
            # fallback behavior (simple and stable)
            intent = _intent_from_text_fallback(text)
            action = "route"

        # Clarify question
        if action == "ask_clarify":
            q = out.get("question") or "Poti clarifica ce vrei sa faci?"
            state["reply"] = q
            state["next_agent"] = None
            return state

        # Public navigation link proposed
        if ui_context == "public" and intent in {"ci","social"}:
            # Let EntryAgent keep owning this if you want.
            state["next_agent"] = "entry"
            return state

        # Legal agent
        if intent == "legal":
            state["next_agent"] = "legalgov"
            return state

        # HubGov actions
        if action in {"hubgov_slots","hubgov_reserve"}:
            state["next_agent"] = "hubgov"
            state.setdefault("steps", []).append({"hubgov_action": action, "args": out.get("args") or {}})
            return state

        # Normal domain routing
        if intent in {"ci","social","operator"}:
            state["next_agent"] = intent
            return state

        # Unknown
        state["reply"] = "Spune-mi despre ce este vorba (e.g.,de CI, ajutor social, etc) sau o intrebare procedurala."
        state["next_agent"] = None
        return state

