# agents/identifiers.py
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Set

_ALLOWED_INTENTS: Set[str] = {"ci","social","operator","unknown"}

_ALLOWED_OPERATOR_ACTIONS: Set[str] = {
    "list_tasks","list_cases","claim_task","complete_task","advance_case","unknown"
}

# Case lifecycle statuses used in the demo UI / mock backend.
# Keep this aligned with:
#  - templates/operator.html (dropdown values)
#  - services/primarie_local_mock.py (create + update status)
_ALLOWED_CASE_STATUSES: Set[str] = {
    "NEW",
    "SCHEDULED",
    "IN_PROCESS",
    "READY_FOR_PICKUP",
    "CLOSED",
}

def allowed_intents() -> Set[str]:
    return set(_ALLOWED_INTENTS)

def allowed_operator_actions() -> Set[str]:
    return set(_ALLOWED_OPERATOR_ACTIONS)

def allowed_case_statuses() -> Set[str]:
    return set(_ALLOWED_CASE_STATUSES)

def _load_checklist_docs(filename: str) -> List[str]:
    p = Path(__file__).parent / "checklists" / filename
    data = json.loads(p.read_text(encoding="utf-8"))
    docs=set()
    for _t, spec in (data.get("types") or {}).items():
        for d in (spec.get("required_docs") or []):
            if isinstance(d, str):
                docs.add(d)
    return sorted(docs)

def allowed_ci_doc_ids() -> List[str]:
    return _load_checklist_docs("ci.json")

def allowed_social_doc_ids() -> List[str]:
    return _load_checklist_docs("social.json")

def allowed_all_doc_ids() -> List[str]:
    return sorted(set(allowed_ci_doc_ids()) | set(allowed_social_doc_ids()))
