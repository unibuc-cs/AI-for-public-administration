# This is the “router”. It looks at the user message and decides which domain agent should run next.
from __future__ import annotations
from typing import Any
from .base import Agent, AgentState
from .llm_utils import classify_intent_with_llm


USE_LLM = False  # TODO: set to True to use LLM for intent detection

class EntryAgent(Agent):
    name = "entry"

    async def handle(self, state: AgentState) -> AgentState:
        text = state.get("message", "").lower()

        if not USE_LLM:
            # detect intent (TODO: replace with LLM later)
            if "ajutor social" in text or "venit de incluziune" in text or "as" == text.strip():
                state["intent"] = "social"
                state["next_agent"] = "social"
            elif "carte de identitate" in text or "buletin" in text or "ci" in text:
                state["intent"] = "ci"
                state["next_agent"] = "ci"
            elif "slot" in text or "program" in text:
                state["intent"] = "schedule"
                state["next_agent"] = "scheduling"
            elif "task" in text or "dosar" in text or "operator" in text:
                state["intent"] = "operator"
                state["next_agent"] = "operator"
            else:
                # default help
                state["reply"] = (
                    "I can help with:\n"
                    "- carte de identitate (CI)\n"
                    "- ajutor social\n"
                    "- operator (list tasks, list cases)\n"
                    "- or say 'slot' to see appointments."
                )
                state["next_agent"] = None
            return state
        else:
            # NOTES:
            # - we keep the old regex as fallback (production-safe)
            # - we enrich state with entities (slot_id, cnp),
            # - we don’t hardcode “/user-ci” in the agent — UI still decides how to present it, based on steps.
            text = state.get("message", "")

            # 1) ask LLM
            try:
                res = await classify_intent_with_llm(text)

                # enforce sanity
                intent = res.get("intent") or "help"
                entities = res.get("entities") or {}
                if "slot_id" not in entities:
                    entities["slot_id"] = None

                state["intent"] = intent
                state["entities"] = entities
            except Exception:
                # 2) fallback to keyword if LLM fails
                low = text.lower()
                if "ajutor social" in low:
                    state["intent"] = "social"
                elif "carte de identitate" in low or "buletin" in low or "ci" in low:
                    state["intent"] = "ci"
                else:
                    state["intent"] = "help"

            # 3) map intent -> next agent
            intent = state["intent"]
            if intent == "ci":
                state["next_agent"] = "ci"
            elif intent == "social":
                state["next_agent"] = "social"
            elif intent == "scheduling":
                state["next_agent"] = "scheduling"
            elif intent == "operator":
                state["next_agent"] = "operator"
            else:
                state["reply"] = (
                    "I can help with CI, Social Aid, scheduling, or operator tasks. "
                    "Tell me which flow you want."
                )
                state["next_agent"] = None

