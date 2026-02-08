# agents/router_agent.py
from __future__ import annotations

import re
from typing import Any, Dict

from .base import Agent, AgentState
from .settings import LLM_USE
from .llm_utils import (
    route_with_llm,
    detect_language_with_llm,
    detect_yesno_with_llm,
    get_domain_from_ui_context,
)
from .entry_agent import _intent_from_text_fallback
from .history import CONTROL_MARKERS, START_MARKER
from services.text_chat_messages import translate_msg


def _looks_like_lang_choice(text: str) -> str | None:
    s = (text or "").strip().lower()
    if s in ("ro", "romana", "romanian") or s.startswith("roman"):
        return "ro"
    if s in ("en", "english"):
        return "en"
    return None


def _looks_like_yes(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(re.match(r"^(da+|yes+|y+|ok+|okay+|sigur+)[!?. ]*$", t))


def _looks_like_no(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(re.match(r"^(nu+|no+|n+|cancel+|ignore+)[!?. ]*$", t))


def looks_like_scheduling(text: str) -> bool:
    t = (text or "").lower()
    keys = [
        "programare", "slot", "rezerva", "reprogram", "cand e liber",
        "programari", "programat", "appointment", "schedule",
    ]
    return any(k in t for k in keys)


class RouterAgent(Agent):
    name = "router"

    async def handle(self, state: AgentState) -> AgentState:
        text = (state.get("message") or "").strip()
        app = state.get("app") or {}
        ui_context = (app.get("ui_context") or "entry").lower() if isinstance(app, dict) else "entry"

        # 0) Language selection first (UI sends __start__ on load).
        if isinstance(app, dict) and not app.get("lang"):
            choice = _looks_like_lang_choice(text)
            if choice:
                app["lang"] = choice
                state["app"] = app
                state["reply"] = translate_msg(app, "lang_set_ro" if choice == "ro" else "lang_set_en")
                state["next_agent"] = "entry"
                return state

            # Try to guess language with LLM
            if LLM_USE and text and (text not in CONTROL_MARKERS) and (text != "__start__"):
                guessed = await detect_language_with_llm(text)
                if guessed in ("ro", "en"):
                    app["lang"] = guessed
                    state["app"] = app
                    state["reply"] = translate_msg(app, "lang_set_ro" if guessed == "ro" else "lang_set_en")
                    state["next_agent"] = "entry"
                    return state

            # If no valid language choice, prompt user to choose at start
            if text == START_MARKER:
                state["reply"] = translate_msg(app, "choose_lang")
                state["next_agent"] = "entry"
                return state

        # Control markers must not go through normal routing
        if text in CONTROL_MARKERS:
            if text == "__upload__":
                state["next_agent"] = "doc_intake"
            else:
                state["next_agent"] = get_domain_from_ui_context(ui_context)
            return state

        if not text:
            state["next_agent"] = "entry"
            return state

        # Autofill confirmation gate (after OCR)
        if isinstance(app, dict) and app.get("pending_autofill_offer"):
            dec = None
            if _looks_like_yes(text):
                dec = "yes"
            elif _looks_like_no(text):
                dec = "no"
            elif LLM_USE:
                dec = await detect_yesno_with_llm(text, topic="autofill")

            if dec == "yes":
                fields = app.get("pending_autofill_fields") or {}
                state.setdefault("steps", []).append({
                    "type": "autofill_apply",
                    "payload": {"fields": fields}
                })
                app["pending_autofill_offer"] = False
                app["pending_autofill_fields"] = {}
                state["app"] = app
                state["reply"] = translate_msg(app, "autofill_applied")
                state["next_agent"] = get_domain_from_ui_context(ui_context)
                return state

            if dec == "no":
                app["pending_autofill_offer"] = False
                app["pending_autofill_fields"] = {}
                state["app"] = app
                state["reply"] = translate_msg(app, "autofill_ignored")
                state["next_agent"] = get_domain_from_ui_context(ui_context)
                return state

            state["reply"] = translate_msg(app, "autofill_ask")
            state["next_agent"] = "router"
            return state

        # 1) Scheduling direct route (keyword fallback even without LLM)
        if looks_like_scheduling(text):
            state["next_agent"] = "scheduling"
            return state

        # 2) LLM route (if enabled), else fallback keywords
        intent = None
        action = None
        if LLM_USE:
            try:
                out = await route_with_llm(text, state.get("history_llm", []))
                intent = (out.get("intent") or "").strip().lower()
                action = (out.get("action") or "").strip().lower()
            except Exception:
                intent = None
                action = None

        if action == "scheduling_help":
            state["next_agent"] = "scheduling"
            return state

        if action in ("hubgov_slots", "hubgov_reserve"):
            # Let HubGov agent handle hub actions (CEI only)
            state.setdefault("steps", []).append({
                "type": "hubgov_action",
                "payload": {"action": action, "args": {"program": app.get("program")}}
            })
            state["next_agent"] = "hubgov"
            return state

        if intent in ("legal",):
            state["next_agent"] = "legal_gov"
            return state

        if intent in ("carte_identitate", "social", "operator"):
            state["next_agent"] = intent
            return state

        # fallback intent if no LLM decision
        fb = _intent_from_text_fallback(text)
        if fb == "scheduling":
            state["next_agent"] = "scheduling"
            return state
        if fb in ("carte_identitate", "social", "operator"):
            state["next_agent"] = fb
            return state

        # Clarify if we got low confidence or an "ask_clarify" action from LLM
        state["reply"] = translate_msg(app, "router_ask_need")
        state["next_agent"] = get_domain_from_ui_context(ui_context)
        return state
