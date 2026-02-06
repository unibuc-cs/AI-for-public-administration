# agents/router_agent.py
from __future__ import annotations

from typing import Any, Dict

from .base import Agent, AgentState
from .settings import LLM_USE
from .llm_utils import (
    route_with_llm,
    _ALLOWED_INTENTS,
    _ALLOWED_ACTIONS,
    _ALLOWED_INTENTS_WITH_AGENTS,
    get_domain_from_ui_context,
)
from .entry_agent import _intent_from_text_fallback
from .history import CONTROL_MARKERS
from services.text_chat_messages import translate_msg

def _is_yes(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {"yes", "y", "da", "ok", "okay", "apply", "confirm", "sigur"}


def _is_no(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {"no", "n", "nu", "cancel", "ignore"}


def looks_like_scheduling(text: str) -> bool:
    t = (text or "").lower()
    keys = [
        "programare", "slot", "rezerva", "reprogram", "cand e liber",
        "programari", "programat", "vreau o programare"
    ]
    return any(k in t for k in keys)

def _looks_like_lang_choice(text: str) -> str | None:
    s = (text or "").strip().lower()
    if s in ("ro", "romana", "romanian"):
        return "ro"
    if s in ("en", "english", "engleza"):
        return "en"
    return None


class RouterAgent(Agent):
    name = "router"

    async def handle(self, state: AgentState) -> AgentState:
        text = (state.get("message") or "").strip()
        app = state.get("app") or {}
        ui_context = (app.get("ui_context") or "entry").lower() if isinstance(app, dict) else "entry"

        if not text:
            state["next_agent"] = "entry"  # safe default
            return state

        # Intercept language if not set yet, ask for it (except control markers)
        if isinstance(app, dict) and not app.get("lang"):
            choice = _looks_like_lang_choice(text)
            if choice:
                app["lang"] = choice
                state["app"] = app
                state["reply"] = translate_msg(app, "lang_set_ro" if choice else "lang_set_en")

                # Continue to router to the same agent to re-route based on new language context
                state["next_agent"] = "router"
                return state

            # Not a choice yet -> ask for it
            # Allow control markers to pass through without forcing the question
            if text not in CONTROL_MARKERS:
                state["reply"] = translate_msg(app, "choose_lang")
                state["next_agent"] = "entry"
                return state



        # Control markers from UI or other components must NOT go through the normal routing.
        # They are used to trigger internal agents (e.g., doc upload, scheduling, OCR, etc).
        if text in CONTROL_MARKERS:
            if text in {"__upload__", "__ping__"}:
                # After an upload marker, go to the doc intake/OCR agent to process file, then set next_agent to the current wizard (e.g., CI/social, operator).
                state["next_agent"] = "doc_intake"
                state["return_to"] = get_domain_from_ui_context(ui_context)
                return state

            # For state phases (e.g., phase1, phase2) route to the current domain agent directly to recheck the state.
            if text in {"__phase1_done__", "__phase2_done__"}:
                state["next_agent"] = get_domain_from_ui_context(ui_context)
                return state

        # Autofill confirmation intercept (do NOT route to LLM)
        if isinstance(app, dict) and app.get("pending_autofill_offer") and isinstance(app.get("pending_autofill_fields"), dict):
            fields = app.get("pending_autofill_fields") or {}

            if _is_yes(text) and fields:
                # Emit typed step to apply autofill in frontend
                state.setdefault("steps", []).append({
                    "type": "autofill_apply",
                    "payload": {"fields": fields}
                })

                # Clear pending autofill state so it does not repeat
                app["pending_autofill_fields"] = {}
                app["pending_autofill_offer"] = False
                state["app"] = app  # ensure app updates are saved in state

                state["reply"] = "Ok. I applied the extracted fields to the form."
                state["next_agent"] = get_domain_from_ui_context(ui_context)  # route back to current domain agent
                return state

            if _is_no(text):
                # Rejected
                app["pending_autofill_fields"] = {}
                app["pending_autofill_offer"] = False
                state["app"] = app

                state["reply"] = "Ok. I will not apply OCR values."
                state["next_agent"] = get_domain_from_ui_context(ui_context)
                return state

        # Keyword-based scheduling fallback when LLM is off or uncertain
        if (not LLM_USE) and looks_like_scheduling(text):
            state["next_agent"] = "scheduling"
            return state

        out: Dict[str, Any] = {}
        if LLM_USE:
            try:
                history = state.get("history") or []

                # ensure the current message is present as last user turn
                if not history or history[-1].get("role") != "user":
                    history = history + [{"role": "user", "content": text}]

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
            # fallback behavior
            if looks_like_scheduling(text):
                action = "scheduling_help"
                intent = "unknown"
            else:
                intent = _intent_from_text_fallback(text)
                action = "route"

        if action == "ask_clarify":
            q = out.get("question") or "Can you clarify what you want to do?"
            state["reply"] = q
            state["next_agent"] = None
            return state

        # Let EntryAgent own public navigation
        if ui_context == "entry" and intent in {"carte_identitate", "social"}:
            state["next_agent"] = "entry"
            return state

        # Legal agent
        if intent == "legal":
            state["next_agent"] = "legalgov"
            return state

        # HubGov actions
        if action in {"hubgov_slots", "hubgov_reserve"}:
            state["next_agent"] = "hubgov"
            state.setdefault("steps", []).append({
                "type": "hubgov_action",
                "payload": {"action": action, "args": out.get("args") or {}}
            })
            return state

        # Scheduling actions
        if action == "scheduling_help":
            state["next_agent"] = "scheduling"
            return state

        # Normal domain routing
        if intent in _ALLOWED_INTENTS_WITH_AGENTS:
            state["next_agent"] = intent
            return state

        # Unknown
        state["reply"] = "Spune-mi despre ce este vorba (e.g.,de CI, ajutor social, etc) sau o intrebare procedurala."
        state["next_agent"] = None
        return state

