# agents/entry_agent.py
# Router agent: decides which domain agent runs next, or emits UI navigation steps.

from __future__ import annotations
from typing import Any, Dict

from .base import Agent, AgentState
from .settings import LLM_USE
from .identifiers import allowed_intents
from .llm_utils import classify_intent_with_llm

_INTENTS = allowed_intents()

def _intent_from_text_fallback(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["ajutor social", "social", "vmi", "venit minim", "benefici"]):
        return "social"
    if any(k in t for k in ["carte de identitate", "buletin", "ci", "c.i."]):
        return "ci"
    if any(k in t for k in ["operator", "task", "tasks", "case", "caz", "dosar"]):
        return "operator"
    return "unknown"

class EntryAgent(Agent):
    name = "entry"

    async def handle(self, state: AgentState) -> AgentState:
        text = state.get("message", "") or ""
        sid = state.get("session_id", "") or ""
        app = state.get("app") or {}

        if isinstance(app, dict):
            ui_context = (app.get("ui_context") or "public").lower()
        else:
            ui_context = (getattr(app, "ui_context") or "public").lower()

        # 1) Decide intent (LLM if enabled; otherwise fallback)
        intent = None
        llm_meta: Dict[str, Any] = {}
        if LLM_USE:
            try:
                out = await classify_intent_with_llm(text)
                cand = (out.get("intent") or "").strip().lower()
                intent = cand if cand in _INTENTS else "unknown"
                llm_meta = out if isinstance(out, dict) else {}
            except Exception:
                intent = None

        if not intent:
            intent = _intent_from_text_fallback(text)

        state.setdefault("steps", []).append({"intent": intent, "ui_context": ui_context, "llm": bool(LLM_USE and llm_meta)})

        # 2) If we are on the PUBLIC chat, prefer navigation for CI / Social
        if ui_context == "public" and intent in {"ci", "social"}:
            url = f"/user-ci?sid={sid}" if intent == "ci" else f"/user-social?sid={sid}"
            label = "Deschide formular CI" if intent == "ci" else "Deschide formular Ajutor Social"
            state.setdefault("steps", []).append({"navigate": {"url": url, "label": label}})
            # Keep reply simple; the widget will render as clickable link.
            state["reply"] = f"Te pot ajuta. {label}: {url}"
            state["next_agent"] = None
            return state

        # 3) Route to domain agents (useful on form pages, for doc-checking and guided Q&A)
        if intent == "ci":
            state["next_agent"] = "ci"
            return state
        if intent == "social":
            state["next_agent"] = "social"
            return state
        if intent == "operator":
            state["next_agent"] = "operator"
            return state

        state["reply"] = (
            "Pot ajuta cu: carte de identitate (CI), ajutor social (VMI), "
            "programări și întrebări de operator (task-uri/cazuri). "
            "Spune-mi ce ai nevoie."
        )
        state["next_agent"] = None
        return state
