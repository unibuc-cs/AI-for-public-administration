# agents/doc_intake_agent.py
# Pull OCR-recognized docs from /local/uploads and normalize them into canonical identifiers.

from __future__ import annotations
import re
import httpx
from typing import List, Optional

from .base import Agent, AgentState
from .settings import LLM_USE, env_flag
from .identifiers import allowed_all_doc_ids
from .llm_utils import normalize_doc_id_with_llm

LOCAL_URL = None  # resolved lazily via agents.tools (shared RUN_MODE logic)


# Small rule-based normalizer (works without LLM)
_RULES = [
    (r"nastere|certificat", "cert_nastere"),
    (r"ci\s*vech|buletin\s*vech|vechea\s*ci", "ci_veche"),
    (r"dovad|adresa|locuint|contract", "dovada_adresa"),
    (r"politi|declaratie\s*politie", "politie"),

    (r"cerere|formular", "cerere_ajutor"),
    (r"carte\s*ident|ci|buletin", "carte_identitate"),
    (r"venit|salariu|adeverinta", "acte_venit"),
    (r"locuir|chirie|utilitat", "acte_locuire"),
    (r"familie|copil|casator", "acte_familie"),
    (r"iban|cont|bancar", "cont_bancar"),
]

def _normalize_rule_based(label: str) -> Optional[str]:
    s = (label or "").strip().lower()
    if not s:
        return None
    for pat, doc_id in _RULES:
        if re.search(pat, s):
            return doc_id
    return None

class DocIntakeAgent(Agent):
    name = "doc_intake"

    async def handle(self, state: AgentState) -> AgentState:
        from .tools import LOCAL_URL as _LOCAL_URL  # use consistent RUN_MODE defaults

        sid = state.get("session_id")
        if not sid:
            state["reply"] = "Lipsește session_id pentru încărcări."
            state["next_agent"] = None
            return state

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{_LOCAL_URL}/uploads", params={"session_id": sid})
            r.raise_for_status()
            uploads = r.json().get("uploads", [])

        allow = allowed_all_doc_ids()
        docs: List[str] = []
        for u in uploads:
            # mock OCR provides a "canonical" field sometimes; fallback to label/name
            label = u.get("canonical") or u.get("label") or u.get("filename") or ""
            # 1) rule-based guess
            doc_id = _normalize_rule_based(label)

            # 2) optional LLM normalization
            if (doc_id is None) and LLM_USE and env_flag("DOC_NORMALIZE_WITH_LLM", True):
                try:
                    out = await normalize_doc_id_with_llm(label, allow)
                    cand = out.get("doc_id")
                    if isinstance(cand, str) and cand in allow:
                        doc_id = cand
                except Exception:
                    doc_id = None

            # 3) validate + collect
            if doc_id and doc_id in allow and doc_id not in docs:
                docs.append(doc_id)

        app = state.get("app") or {}
        app["docs"] = docs
        state["app"] = app

        state.setdefault("steps", []).append({"ocr_docs": docs})

        # Return control to the caller agent
        return_to = state.pop("return_to", None)
        state["next_agent"] = return_to  # may be "social" or "ci"
        return state
