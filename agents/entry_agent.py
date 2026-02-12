# agents/entry_agent.py
# Entry agent: decides which domain agent runs next, or emits UI navigation steps.

from __future__ import annotations

from .base import Agent, AgentState
from .settings import LLM_USE
from .identifiers import allowed_intents
from .llm_utils import classify_intent_with_llm
from .routing_keywords import keyword_intent
from services.text_chat_messages import translate_msg
from .case_registry import get_case_config
_INTENTS = allowed_intents()

from .llm_utils import get_domain_from_ui_context  # add this

class EntryAgent(Agent):
    name = "entry"

    async def handle(self, state: AgentState) -> AgentState:
        text = state.get("message", "") or ""
        app = state.get("app") or {}
        ui_context = (app.get("ui_context") or "public").lower() if isinstance(app, dict) else "public"

        # If we are inside a wizard page, route to that wizard's domain agent.
        if ui_context in {"carte_identitate", "social", "operator", "taxe"}:
            state["next_agent"] = get_domain_from_ui_context(ui_context)
            return state

        # Decide intent (LLM if enabled; else keyword fallback)
        intent = None
        if LLM_USE:
            try:
                out = await classify_intent_with_llm(text)
                cand = (out.get("intent") or "").strip().lower()
                intent = cand if cand in _INTENTS else "unknown"
            except Exception:
                intent = None
        if not intent:
            intent = keyword_intent(text)

        # Navigate using registry (single place)
        cfg = get_case_config(intent)
        if cfg and cfg.ui_path:
            sid = state.get("session_id", "") or ""
            state.setdefault("steps", []).append({
                "type": "navigate",
                "payload": {"path": f"{cfg.ui_path}?sid={sid}"}
            })
            state["reply"] = translate_msg(app, "entry_nav_link", label=cfg.title, url=f"{cfg.ui_path}?sid={sid}")
            state["next_agent"] = None
            return state

        # Non-wizard intents
        if intent == "scheduling":
            state["next_agent"] = "scheduling"
            return state
        if intent == "legal":
            state["next_agent"] = "legalgov"
            return state
        if intent == "operator":
            state["next_agent"] = "operator"
            return state

        state["reply"] = translate_msg(app, "entry_help")
        state["next_agent"] = None
        return state
