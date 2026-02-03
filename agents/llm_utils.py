# agents/llm_utils.py
# LLM helpers used by EntryAgent / OperatorAgent / DocIntakeAgent.
# All functions are defensive: they return structured JSON and are validated by the caller.

from __future__ import annotations
import os
import json
from typing import Dict, Any, List, Optional
from openai import AsyncOpenAI

from .settings import LLM_MODEL

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_ALLOWED_INTENTS = {"ci","social","operator","legal","unknown"}
_ALLOWED_ACTIONS = {"route","navigate","ask_clarify","hubgov_slots","hubgov_reserve","unknown"}

actions_union = '"|"'.join(sorted(_ALLOWED_ACTIONS))
intents_union = '"|"'.join(sorted(_ALLOWED_INTENTS))

ROUTER_SYS_PROMPT = f"""You are an intent classifier for a Romanian e-gov assistant.
Return ONLY JSON with this schema:
{{
  "intent": "{intents_union}",
  "action": "{actions_union}",
  "confidence": 0.0-1.0,
  "question": string|null,
  "args": {{ "cnp": string|null, "app_type": string|null, "location_id": string|null, "slot_id": string|null }},
  "reason": string
}}

Rules:
- The user can write anything. If ambiguous, action="ask_clarify" and set question.
- Use intent="legal" for legal/procedure questions.
- Use hubgov_* actions only for electronic ID (cei).
- Keep question short and concrete.
- question is required only when action == "ask_clarify".
- Output must be a single JSON object instance, not the schema. Use actual JSON values: strings in quotes, null as null, numbers as numbers.
- If you ask a question, ask it in Romanian.
- No markdown, no code fences.
- keep reason short <= 20 words
"""

INTENT_SYS_PROMPT = """You are an intent classifier for a Romanian e-gov assistant.

Return ONLY JSON with this schema:
{
  "intent": "ci" | "social" | "operator" | "unknown",
  "confidence": 0.0-1.0,
  "entities": {
      "cnp": string|null,
      "name": string|null,
      "email": string|null
  },
  "reason": string
}

Rules:
- "ci" for carte de identitate / buletin / CI.
- "social" for ajutor social / beneficii / VMI/ venit minim incluziune.
- "operator" for backoffice: tasks/cases/admin actions.
- "unknown" otherwise.
"""

OPERATOR_SYS_PROMPT_TEMPLATE = """You are a command parser for a Romanian public administration operator console.

Convert the operator's message into ONE action.

Supported actions:
- list_tasks
- list_cases
- claim_task (requires task_id:int)
- complete_task (requires task_id:int)
- advance_case (requires case_id:str, status:str)

Allowed case statuses for advance_case:
{allowed_statuses}

Return ONLY JSON with this schema:
{
  "action": "list_tasks"|"list_cases"|"claim_task"|"complete_task"|"advance_case"|"unknown",
  "task_id": int|null,
  "case_id": string|null,
  "status": string|null,
  "confidence": 0.0-1.0,
  "reason": string
}

If unclear, use action="unknown".
"""

DOC_NORMALIZE_SYS_PROMPT = """You normalize OCR document labels into canonical identifiers.

Return ONLY JSON:
{
  "doc_id": string|null,
  "confidence": 0.0-1.0,
  "reason": string
}

Only choose a doc_id from this allowlist:
{allowlist}

If you cannot map confidently, return doc_id=null.
"""


# Can either pass a list of messages or a single string (user message).
async def _call_json(system_prompt: str,
                     messages: List[Dict[str, str]] | str ) -> Dict[str, Any]:

    # Uses OpenAI-style JSON mode. Caller must still validate.
    resp = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": system_prompt}] + messages if isinstance(messages,    list)
            else [{"role": "system", "content": system_prompt}, {"role": "user", "content": messages}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    raw = resp.choices[0].message.content
    return json.loads(raw)

async def route_with_llm(history_messages: List[Dict[str, str]]) -> Dict[str, Any]:
    return await _call_json(ROUTER_SYS_PROMPT, history_messages)

async def classify_intent_with_llm(user_message: str) -> Dict[str, Any]:
    return await _call_json(INTENT_SYS_PROMPT, user_message)

async def parse_operator_command_with_llm(user_message: str, allowed_statuses: List[str]) -> Dict[str, Any]:
    prompt = OPERATOR_SYS_PROMPT_TEMPLATE.format(
        allowed_statuses=", ".join(allowed_statuses)
    )
    return await _call_json(prompt, user_message)

async def normalize_doc_id_with_llm(ocr_label: str, allowlist: List[str]) -> Dict[str, Any]:
    prompt = DOC_NORMALIZE_SYS_PROMPT.format(allowlist=", ".join(allowlist))
    return await _call_json(prompt, ocr_label)
