# agents/entry_agent.py
# Router agent: decides which domain agent runs next, or emits UI navigation steps.

from __future__ import annotations
from typing import Any, Dict

import db
from .base import Agent, AgentState
from .settings import LLM_USE
from .identifiers import allowed_intents
from .llm_utils import classify_intent_with_llm
from services.text_chat_messages import translate_msg

_INTENTS = allowed_intents()

def _intent_from_text_fallback(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ["ajutor social", "social", "vmi", "venit minim", "benefici"]):
        return "social"
    if any(k in t for k in ["carte de identitate", "buletin", "ci", "c.i."]):
        return "carte_identitate"
    if any(k in t for k in ["operator", "task", "tasks", "case", "caz", "dosar"]):
        return "operator"
    if any(k in t for k in ["programare", "slot", "rezerva", "reprogram", "cand e liber", "programari", "programat"]):
        return "scheduling"
    return "unknown"

class EntryAgent(Agent):
    name = "entry"

    async def handle(self, state: AgentState) -> AgentState:
        text = state.get("message", "") or ""
        sid = state.get("session_id", "") or ""
        app = state.get("app") or {}

        ui_context = (app.get("ui_context") or "public").lower() if isinstance(app, dict) else "public"

        # If we are already inside a specific wizard, route directly.
        if ui_context in {"carte_identitate", "social", "operator"}:
            state["next_agent"] = ui_context
            return state

        # 1) Decide intent (LLM if enabled; otherwise fallback)
        intent = None
        if LLM_USE:
            try:
                out = await classify_intent_with_llm(text)
                cand = (out.get("intent") or "").strip().lower()
                intent = cand if cand in _INTENTS else "unknown"
            except Exception:
                intent = None

        if not intent:
            intent = _intent_from_text_fallback(text)

        # 2) Public chat: navigate for CI/Social
        if ui_context == "public" and intent in {"carte_identitate", "social"}:
            # Generate navigation step to the appropriate form page
            # First sid
            newsid = db.getRandomSessionId()
            url = f"/user-ci?sid=ci-{newsid}" if intent == "carte_identitate" else f"/user-social?sid=social-{newsid}"
            label = "Deschide formularul Evidenta Persoane" if intent == "carte_identitate" else "Deschide formular Ajutor Social"

            state.setdefault("steps", []).append({
                "type": "navigate",
                "payload": {"url": url, "label": label}
            })
            state["reply"] = translate_msg(app, "entry_nav_link", label=label, url=url)
            state["next_agent"] = None
            return state

        # 3) Route to domain agents (useful on form pages, for doc-checking and guided Q&A)
        if intent == "carte_identitate":
            state["next_agent"] = "carte_identitate"
            return state
        if intent == "social":
            state["next_agent"] = "social"
            return state
        if intent == "operator":
            state["next_agent"] = "operator"
            return state
        if intent == "scheduling":
            state["next_agent"] = "scheduling"
            return state
			
        state["reply"] = translate_msg(app, "entry_help")
        state["next_agent"] = None
        return state
