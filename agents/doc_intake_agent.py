# This pulls OCR-recognized docs from  /local/uploads.
# LLM usage: e.g., normalize document names
# User says: “am pus poza cu certificatul copilului”. OCR says: certificat copil. You want canonical cert_nastere.

# TODO: DocIntake Agent, for each OCR label, you run this and store the canonical one.

from __future__ import annotations
import os
import httpx
from .base import Agent, AgentState
from .llm_utils import client

LOCAL_URL = os.getenv("LOCAL_URL", "http://127.0.0.1:8000/local")


NORMALIZE_PROMPT = """Map the following Romanian document description to one of the canonical keys:
- cert_nastere
- ci_veche
- dovada_adresa
- cerere_ajutor
- acte_venit
- acte_locuire
If you can't decide, return "unknown".
Return JSON: {"canonical": "..."}.
"""

async def normalize_doc_name(text: str) -> str:
    resp = await client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": NORMALIZE_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    import json
    j = json.loads(resp.choices[0].message.content)
    return j.get("canonical", "unknown")


class DocIntakeAgent(Agent):
    name = "doc_intake"

    async def handle(self, state: AgentState) -> AgentState:
        sid = state["session_id"]
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{LOCAL_URL}/uploads", params={"session_id": sid})
                j = r.json()
        except Exception:
            j = {"recognized": []}

        docs = [{"kind": k, "status": "ok"} for k in j.get("recognized", [])]
        app = state.get("app") or {}
        if not app.get("docs"):
            app["docs"] = docs
        state["app"] = app

        # don’t decide next_agent here — let caller decide
        state.setdefault("steps", []).append({"ocr_docs": docs})
        return state
