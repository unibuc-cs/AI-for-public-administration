# agents/identifiers.py
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Set

_ALLOWED_INTENTS: Set[str] = {"carte_identitate","social","operator","taxe","unknown"}

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
    docs: Set[str] = set()

    # Support both schemas:
    #  A) {"required_docs": [...]} (simple)
    #  B) {"types": {"X": {"required_docs": [...]}}} (by type)
    for d in (data.get("required_docs") or []):
        if isinstance(d, str) and d:
            docs.add(d)

    for _t, spec in (data.get("types") or {}).items():
        for d in (spec.get("required_docs") or []):
            if isinstance(d, str) and d:
                docs.add(d)

    return sorted(docs)

def allowed_ci_doc_ids() -> List[str]:
    return _load_checklist_docs("ci.json")

def allowed_social_doc_ids() -> List[str]:
    return _load_checklist_docs("social.json")

def allowed_all_doc_ids() -> List[str]:
    return sorted(set(allowed_ci_doc_ids()) | set(allowed_social_doc_ids()))

# ---------------------------------------------------------------------------
# Doc catalog helpers (labels/hints for UI messages and prompts)
# ---------------------------------------------------------------------------

_DOC_CATALOG_PATH = Path(__file__).parent / "checklists" / "doc_catalog.json"

def load_doc_catalog() -> dict:
    try:
        return json.loads(_DOC_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def doc_label(doc_id: str) -> str:
    cat = load_doc_catalog()
    entry = cat.get(doc_id) or {}
    return entry.get("label") or doc_id

def docs_as_cards(doc_ids: list[str]) -> list[dict]:
    cat = load_doc_catalog()
    cards: list[dict] = []
    for did in doc_ids:
        entry = cat.get(did) or {}
        cards.append({
            "id": did,
            "label": entry.get("label") or did,
            "hints": entry.get("hints") or [],
        })
    return cards
