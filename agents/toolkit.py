# agents/toolkit.py
# Typed tool registry for the v2 agent harness.
#
# Design rule: "prose proposes, tools dispose".
# Skills (SKILL.md) describe a procedure in natural language; they cannot waive a
# check defined here. Every legally-relevant gate — checklist satisfaction, document
# validity, permission scopes, case-status transitions — lives in this layer as code,
# is permission-checked, and is written to the audit log.
#
# The registry doubles as the machine-readable tool set `T` consumed by the ABSORB
# triage pipeline (see Doc/absorption-framework-plan.md, Def. 1).

from __future__ import annotations

import inspect
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException

from audit import write_audit
from services.auth import assert_actor_perm

from . import rag
from .identifiers import allowed_case_statuses, docs_as_cards, doc_label
from .tools import (
    HUB_URL,
    LOCAL_URL,
    tool_case_submit,
    tool_schedule_by_slot,
    tool_schedule_social_by_slot,
)
from .http_client import make_async_client

_KB_PATH = Path(__file__).resolve().parent.parent / "kb" / "procedure.json"
_DOC_RULES_PATH = Path(__file__).parent / "checklists" / "doc_rules.json"


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]          # JSON Schema for the arguments
    handler: Callable
    scope: Optional[str] = None         # permission required, None = public/citizen
    audit_action: Optional[str] = None  # audit action name; None = not audited
    tags: List[str] = field(default_factory=list)


TOOLS: Dict[str, ToolSpec] = {}


def tool(name: str, description: str, parameters: Dict[str, Any],
         scope: Optional[str] = None, audit_action: Optional[str] = None,
         tags: Optional[List[str]] = None):
    """Register a function as a harness tool."""
    def deco(fn: Callable) -> Callable:
        TOOLS[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=fn,
            scope=scope,
            audit_action=audit_action,
            tags=tags or [],
        )
        return fn
    return deco


def _obj(props: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


_STR = {"type": "string"}
_INT = {"type": "integer"}


def tools_for_actor(actor: Optional[dict]) -> List[ToolSpec]:
    """Only tools the actor is permitted to call are ever shown to the model.

    Permission is enforced again at execution time; this filter exists so the
    model is not tempted by capabilities it cannot use.
    """
    out: List[ToolSpec] = []
    for spec in TOOLS.values():
        if spec.scope:
            try:
                assert_actor_perm(actor or {}, spec.scope)
            except HTTPException:
                continue
        out.append(spec)
    return out


def openai_schema(spec: ToolSpec) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


async def execute_tool(name: str, args: Dict[str, Any], actor: Optional[dict],
                       session_id: str = "") -> Dict[str, Any]:
    """Execute a tool with permission check + audit. Never raises to the caller.

    Errors come back as {"error": ...} so the model can recover in-loop instead of
    the request failing. Permission denials are audited.
    """
    spec = TOOLS.get(name)
    if not spec:
        return {"error": "unknown_tool", "detail": f"No tool named {name!r}."}

    if spec.scope:
        try:
            assert_actor_perm(actor or {}, spec.scope)
        except HTTPException:
            write_audit(
                actor=(actor or {}).get("sub", "anonymous"),
                action="TOOL_DENIED",
                entity_type="tool",
                entity_id=name,
                details={"scope": spec.scope, "session_id": session_id},
            )
            return {"error": "forbidden",
                    "detail": f"Tool {name!r} requires permission {spec.scope!r}."}

    try:
        if inspect.iscoroutinefunction(spec.handler):
            result = await spec.handler(**(args or {}))
        else:
            result = spec.handler(**(args or {}))
    except TypeError as e:
        return {"error": "bad_arguments", "detail": str(e)}
    except HTTPException as e:
        return {"error": "forbidden", "detail": str(e.detail)}
    except Exception as e:  # tool failures are data, not crashes
        return {"error": "tool_failed", "detail": f"{type(e).__name__}: {e}"}

    if spec.audit_action:
        write_audit(
            actor=(actor or {}).get("sub", "anonymous"),
            action=spec.audit_action,
            entity_type="tool",
            entity_id=name,
            details={"session_id": session_id, "args": _audit_safe(args)},
        )

    return result if isinstance(result, dict) else {"result": result}


def _audit_safe(args: Dict[str, Any]) -> Dict[str, Any]:
    """Keep argument shape in the audit log without copying PII values.

    write_audit() already redacts known PII keys; this additionally collapses
    nested structures so free-form person payloads never land in the log verbatim.
    """
    out: Dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, (dict, list)):
            out[k] = f"<{type(v).__name__}:{len(v)}>"
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------
# Config readers (deployment-level, declarative)
# --------------------------------------------------------------------------

def _load_kb() -> Dict[str, Any]:
    try:
        return json.loads(_KB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_doc_rules() -> Dict[str, Any]:
    """Per-deployment document rules (validity windows etc.).

    This file is the variability point absorbed from field spec FS-0007: an office
    that rejects proof-of-address older than N days is configuration, not code.
    """
    try:
        return json.loads(_DOC_RULES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Generic checklist resolution
#
# There is deliberately no per-procedure branch here. A checklist file in
# agents/checklists/<procedure>.json defines a procedure; adding a new procedure
# is a config change, not a code change. Both checklist shapes are supported:
#   A) {"required_docs": [...]}
#   B) {"common_docs": [...], "types": {...}, "eligibility_docs": {...}}
# --------------------------------------------------------------------------

_CHECKLIST_DIR = Path(__file__).parent / "checklists"
_NOT_CHECKLISTS = {"doc_catalog", "doc_rules"}
_PROCEDURE_ALIASES = {"carte_identitate": "ci", "as": "social", "tax": "taxe"}


def known_procedures() -> List[str]:
    if not _CHECKLIST_DIR.is_dir():
        return []
    return sorted(p.stem for p in _CHECKLIST_DIR.glob("*.json")
                  if p.stem not in _NOT_CHECKLISTS and not p.stem.startswith("_"))


def _canonical_procedure(procedure: str) -> str:
    p = (procedure or "").strip().lower()
    return _PROCEDURE_ALIASES.get(p, p)


def _load_checklist(procedure: str) -> Dict[str, Any]:
    path = _CHECKLIST_DIR / f"{_canonical_procedure(procedure)}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def required_docs(procedure: str, app_type: str | None = None,
                  eligibility_reason: str | None = None) -> List[str]:
    cfg = _load_checklist(procedure)
    required: set[str] = set()
    for key in ("required_docs", "common_docs"):
        for d in (cfg.get(key) or []):
            if isinstance(d, str) and d:
                required.add(d)

    t = (app_type or "").strip().upper()
    if t:
        spec = (cfg.get("types") or {}).get(t) or {}
        for d in (spec.get("required_docs") or []):
            if isinstance(d, str) and d:
                required.add(d)

    r = (eligibility_reason or "").strip().upper()
    if r:
        for d in ((cfg.get("eligibility_docs") or {}).get(r) or []):
            if isinstance(d, str) and d:
                required.add(d)

    return sorted(required)


def missing_docs(procedure: str, provided: List[str], app_type: str | None = None,
                 eligibility_reason: str | None = None) -> List[str]:
    have = {d for d in (provided or []) if d}
    return sorted(set(required_docs(procedure, app_type, eligibility_reason)) - have)


# --------------------------------------------------------------------------
# Citizen-facing tools
# --------------------------------------------------------------------------

@tool(
    name="get_checklist",
    description=(
        "Return the authoritative list of documents required for a procedure. "
        "ALWAYS call this before telling the citizen which documents are needed — "
        "never list documents from memory."
    ),
    parameters=_obj({
        "procedure": {**_STR, "enum": known_procedures(),
                      "description": "Procedure key; one checklist file per procedure"},
        "app_type": {**_STR, "description": "For ci only: CEI | CIS | VR"},
        "eligibility_reason": {**_STR,
                               "description": "EXP_60 | AGE_14 | CHANGE_NAME | CHANGE_ADDR | LOSS"},
    }, ["procedure"]),
    tags=["checklist"],
)
def t_get_checklist(procedure: str, app_type: str | None = None,
                    eligibility_reason: str | None = None) -> dict:
    required = required_docs(procedure, app_type, eligibility_reason)
    if not required:
        return {"procedure": procedure, "required": [], "required_cards": [],
                "error": "unknown_procedure", "known": known_procedures()}
    return {"procedure": procedure, "required": required,
            "required_cards": docs_as_cards(required)}


@tool(
    name="check_missing_documents",
    description=(
        "Compare the documents already provided against the checklist and return what is "
        "still missing. Use this to decide whether the citizen can proceed."
    ),
    parameters=_obj({
        "procedure": {**_STR, "enum": known_procedures()},
        "provided": {"type": "array", "items": _STR,
                     "description": "Document kinds already provided, e.g. ['carte_identitate']"},
        "app_type": _STR,
        "eligibility_reason": _STR,
    }, ["procedure", "provided"]),
    tags=["checklist"],
)
def t_check_missing_documents(procedure: str, provided: List[str],
                              app_type: str | None = None,
                              eligibility_reason: str | None = None) -> dict:
    missing = missing_docs(procedure, provided, app_type, eligibility_reason)
    return {"missing": missing, "missing_cards": docs_as_cards(missing),
            "complete": len(missing) == 0}


@tool(
    name="validate_document",
    description=(
        "Validate one uploaded document against deployment rules (accepted kind, and "
        "validity window where the institution requires a recent document). "
        "A document is only usable once this returns valid=true."
    ),
    parameters=_obj({
        "kind": {**_STR, "description": "Canonical doc kind, e.g. dovada_adresa"},
        "issued": {**_STR, "description": "Issue date, ISO format YYYY-MM-DD (if known)"},
    }, ["kind"]),
    audit_action="DOC_VALIDATED",
    tags=["documents"],
)
def t_validate_document(kind: str, issued: str | None = None) -> dict:
    """Enforced semantics: prose can ask for a recent document, only this can reject one."""
    rules = _load_doc_rules()
    kind = (kind or "").strip()
    known = set(_load_kb().get("doc_kinds") or []) | set(rules.keys())
    if kind not in known:
        return {"valid": False, "reason": "unknown_kind", "kind": kind}

    rule = rules.get(kind) or {}
    max_age = rule.get("max_age_days")
    if max_age:
        if not issued:
            return {"valid": False, "reason": "issue_date_required",
                    "kind": kind, "max_age_days": max_age,
                    "message": f"{doc_label(kind)}: data emiterii este obligatorie "
                               f"(document valabil {max_age} zile)."}
        from datetime import date
        try:
            y, m, d = (int(x) for x in issued.split("-"))
            age_days = (date.today() - date(y, m, d)).days
        except Exception:
            return {"valid": False, "reason": "bad_issue_date", "kind": kind}
        if age_days > max_age:
            return {"valid": False, "reason": "doc_too_old", "kind": kind,
                    "age_days": age_days, "max_age_days": max_age,
                    "message": f"{doc_label(kind)}: documentul are {age_days} zile, "
                               f"maxim acceptat {max_age}."}

    return {"valid": True, "kind": kind, "label": doc_label(kind)}


@tool(
    name="list_uploaded_documents",
    description="List the document kinds recognised by OCR for the current session.",
    parameters=_obj({"session_id": _STR}, ["session_id"]),
    tags=["documents"],
)
async def t_list_uploaded_documents(session_id: str) -> dict:
    try:
        async with make_async_client() as client:
            r = await client.get(f"{LOCAL_URL}/uploads", params={"session_id": session_id},
                                 headers={"X-Caller": "harness_list_uploads"})
            j = r.json()
        kinds = j.get("recognized", []) or []
        return {"recognized": kinds, "cards": docs_as_cards(kinds)}
    except Exception as e:
        return {"recognized": [], "error": f"uploads_unavailable: {e}"}


@tool(
    name="get_fees",
    description="Return the fee for a procedure/type from the knowledge base.",
    parameters=_obj({
        "procedure": {**_STR, "enum": ["ci", "social", "taxe"]},
        "app_type": {**_STR, "description": "For ci: CEI | CIS | VR"},
    }, ["procedure"]),
    tags=["kb"],
)
def t_get_fees(procedure: str, app_type: str | None = None) -> dict:
    fees = _load_kb().get("fees") or {}
    if (procedure or "").lower() in {"ci", "carte_identitate"} and app_type:
        spec = fees.get((app_type or "").upper())
        if spec:
            return {"procedure": procedure, "type": app_type.upper(), "fee": spec}
    return {"procedure": procedure, "fees": fees}


@tool(
    name="get_eligibility_rules",
    description="Return the eligibility reasons and their meaning for identity cards.",
    parameters=_obj({}),
    tags=["kb"],
)
def t_get_eligibility_rules() -> dict:
    kb = _load_kb()
    return {"eligibility_rules": kb.get("eligibility_rules") or {},
            "notes": kb.get("notes") or []}


@tool(
    name="kb_search",
    description=(
        "Search the legal/procedural knowledge base and return passages with citations. "
        "Use for questions about law, rules or procedure rather than answering from memory."
    ),
    parameters=_obj({"query": _STR, "k": {**_INT, "default": 3}}, ["query"]),
    tags=["kb"],
)
def t_kb_search(query: str, k: int = 3) -> dict:
    try:
        return {"results": rag.search(query, k)}
    except Exception as e:
        return {"results": [], "error": str(e)}


@tool(
    name="list_slots",
    description=(
        "List available appointment slots. service='hub' for electronic ID (CEI) via CEI-HUB; "
        "service='local' for social-aid appointments at the city hall."
    ),
    parameters=_obj({
        "service": {**_STR, "enum": ["hub", "local"]},
        "location_id": _STR,
    }, ["service"]),
    tags=["scheduling"],
)
async def t_list_slots(service: str, location_id: str | None = None) -> dict:
    params = {"location_id": location_id} if location_id else None
    try:
        async with make_async_client() as client:
            if (service or "").lower() == "hub":
                r = await client.get(f"{HUB_URL}/slots", params=params)
            else:
                r = await client.get(f"{LOCAL_URL}/slots-social", params=params)
            return {"service": service, "slots": r.json()}
    except Exception as e:
        return {"service": service, "slots": [], "error": str(e)}


@tool(
    name="reserve_slot",
    description="Reserve a specific appointment slot the citizen has chosen.",
    parameters=_obj({
        "service": {**_STR, "enum": ["hub", "local"]},
        "slot_id": _STR,
        "cnp": _STR,
    }, ["service", "slot_id"]),
    audit_action="SLOT_RESERVED",
    tags=["scheduling"],
)
async def t_reserve_slot(service: str, slot_id: str, cnp: str | None = None) -> dict:
    if (service or "").lower() == "hub":
        return await tool_schedule_by_slot(slot_id, cnp=cnp)
    return await tool_schedule_social_by_slot(slot_id, cnp=cnp)


@tool(
    name="create_case",
    description=(
        "Submit the citizen's file and create a case. This is the final step. "
        "It refuses if required documents are missing — check with "
        "check_missing_documents first."
    ),
    parameters=_obj({
        "procedure": {**_STR, "enum": known_procedures()},
        "person": {"type": "object", "description": "cnp, nume, prenume, email, telefon"},
        "provided": {"type": "array", "items": _STR},
        "app_type": {**_STR, "description": "For ci: CEI | CIS | VR"},
        "eligibility_reason": _STR,
    }, ["procedure", "person", "provided"]),
    audit_action="CASE_CREATED",
    tags=["case"],
)
async def t_create_case(procedure: str, person: dict, provided: List[str],
                        app_type: str | None = None,
                        eligibility_reason: str | None = None) -> dict:
    """Central enforcement gate: no case is created on an incomplete file.

    A skill may not talk its way past this check — that is the point of the rule
    "prose proposes, tools dispose".
    """
    docs = [{"kind": k, "status": "ok"} for k in (provided or [])]
    if not required_docs(procedure, app_type, eligibility_reason):
        return {"created": False, "error": "unknown_procedure",
                "known": known_procedures()}
    missing = missing_docs(procedure, provided, app_type, eligibility_reason)
    if missing:
        return {"created": False, "error": "incomplete_file", "missing": missing,
                "missing_cards": docs_as_cards(missing),
                "message": "Dosarul este incomplet; nu se poate crea cazul."}

    required_person = ["cnp", "nume", "prenume"]
    absent = [f for f in required_person if not (person or {}).get(f)]
    if absent:
        return {"created": False, "error": "missing_person_fields", "fields": absent}

    prog = {"ci": (app_type or "CEI"), "social": "AS", "taxe": "TAXE"}.get(
        (procedure or "").lower(), "CEI")
    app = {"program": prog, "type": app_type or prog,
           "eligibility_reason": eligibility_reason, "docs": docs}
    case = await tool_case_submit(person or {}, app)
    return {"created": True, **(case if isinstance(case, dict) else {"case": case})}


# --------------------------------------------------------------------------
# Operator tools (permission-scoped)
# --------------------------------------------------------------------------

@tool(
    name="list_tasks",
    description="List human-in-the-loop tasks in the operator queue.",
    parameters=_obj({"status": _STR}),
    scope="case:read",
    tags=["operator"],
)
async def t_list_tasks(status: str | None = None) -> dict:
    async with make_async_client() as client:
        r = await client.get(f"{LOCAL_URL}/tasks",
                             params={"status": status} if status else None)
        j = r.json()
    tasks = j.get("tasks", j) if isinstance(j, dict) else j
    return {"count": len(tasks or []), "tasks": tasks}


@tool(
    name="list_cases",
    description="List cases held by the city hall.",
    parameters=_obj({"type": _STR}),
    scope="case:read",
    tags=["operator"],
)
async def t_list_cases(type: str | None = None) -> dict:
    async with make_async_client() as client:
        r = await client.get(f"{LOCAL_URL}/cases", params={"type": type} if type else None)
        j = r.json()
    cases = j.get("cases", j) if isinstance(j, dict) else j
    return {"count": len(cases or []), "cases": cases}


@tool(
    name="claim_task",
    description="Claim a task from the operator queue.",
    parameters=_obj({"task_id": _INT}, ["task_id"]),
    scope="case:update",
    audit_action="TASK_CLAIMED",
    tags=["operator"],
)
async def t_claim_task(task_id: int) -> dict:
    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/tasks/{int(task_id)}/claim", json={})
        r.raise_for_status()
        return {"task_id": int(task_id), **(r.json() or {})}


@tool(
    name="complete_task",
    description="Mark an operator task as completed.",
    parameters=_obj({"task_id": _INT, "notes": _STR}, ["task_id"]),
    scope="case:update",
    audit_action="TASK_COMPLETED",
    tags=["operator"],
)
async def t_complete_task(task_id: int, notes: str = "") -> dict:
    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/tasks/{int(task_id)}/complete",
                              json={"notes": notes or ""})
        r.raise_for_status()
        return {"task_id": int(task_id), **(r.json() or {})}


@tool(
    name="advance_case",
    description="Move a case to a new status. Only allowlisted statuses are accepted.",
    parameters=_obj({
        "case_id": _STR,
        "status": {**_STR, "enum": sorted(allowed_case_statuses())},
    }, ["case_id", "status"]),
    scope="case:update",
    audit_action="CASE_ADVANCED",
    tags=["operator"],
)
async def t_advance_case(case_id: str, status: str) -> dict:
    """Enforced semantics: the status allowlist is not negotiable by prose."""
    st = (status or "").strip().upper().replace(" ", "_")
    if st not in allowed_case_statuses():
        return {"error": "invalid_status", "status": status,
                "allowed": sorted(allowed_case_statuses())}
    async with make_async_client() as client:
        r = await client.patch(f"{LOCAL_URL}/cases/{case_id}", params={"status": st})
        r.raise_for_status()
        return {"case_id": case_id, "status": st, **(r.json() or {})}


def tool_names() -> List[str]:
    return sorted(TOOLS.keys())
