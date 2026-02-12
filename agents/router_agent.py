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
from .routing_keywords import keyword_intent, looks_like_scheduling
from .history import CONTROL_MARKERS, START_MARKER
from services.text_chat_messages import translate_msg
from .case_registry import get_case_config

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


 


def _greet_key_for_ctx(ui_context: str) -> str:
    ctx = (ui_context or "entry").lower()
    if ctx in ("carte_identitate"):
        return "greet_ci"
    if ctx in ("social"):
        return "greet_social"
    if ctx in ("operator"):
        return "greet_operator"
    return "greet_entry"


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

                lang_msg = translate_msg(app, "lang_set_ro" if choice == "ro" else "lang_set_en")
                greet_msg = translate_msg(app, _greet_key_for_ctx(ui_context))
                state["reply"] = f"{lang_msg} \n\n {greet_msg}"
                state["next_agent"] = "entry"
                return state

            # Try to guess language with LLM
            if LLM_USE and text and (text not in CONTROL_MARKERS) and (text != START_MARKER):
                guessed = await detect_language_with_llm(text)
                if guessed in ("ro", "en"):
                    app["lang"] = guessed
                    state["app"] = app

                    lang_msg = translate_msg(app, "lang_set_ro" if guessed == "ro" else "lang_set_en")
                    greet_msg = translate_msg(app, _greet_key_for_ctx(ui_context))
                    state["reply"] = lang_msg + "\n\n" + greet_msg
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
                out = await route_with_llm(text, state.get("history", []))
                intent = (out.get("intent") or "").strip().lower()
                action = (out.get("action") or "").strip().lower()
            except Exception:
                intent = None
                action = None

            # Prefer registry mapping whenever we have an intent that corresponds to a use case
            cfg = get_case_config(intent or "")
            if cfg:
                state["program"] = cfg.program
                state["next_agent"] = cfg.agent_name
                return state

            if action == "scheduling_help":
                state["next_agent"] = "scheduling"
                return state

            if action in ("hubgov_slots", "hubgov_reserve"):
                state.setdefault("steps", []).append({
                    "type": "hubgov_action",
                    "payload": {"action": action, "args": {"program": state.get("program") or app.get("program")}}
                })
                state["next_agent"] = "hubgov"
                return state

            if intent == "legal":
                state["next_agent"] = "legalgov"
                return state

            # fallback intent if no LLM decision
            fb = keyword_intent(text)
            cfg_fb = get_case_config(fb or "")
            if cfg_fb:
                state["program"] = cfg_fb.program
                state["next_agent"] = cfg_fb.agent_name
                return state
            if fb == "legal":
                state["next_agent"] = "legalgov"
                return state

            # Clarify / continue with current wizard agent
            state["reply"] = translate_msg(app, "router_ask_need")
            state["next_agent"] = get_domain_from_ui_context(ui_context)
            return state
