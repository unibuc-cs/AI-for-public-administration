"""Unit tests for the enforced tool gates (v2 harness).

Usage:
  python -m tests.test_tool_gates

These tests deliberately contain no LLM call. They verify the guarantees that a
skill's prose must not be able to waive — the "prose proposes, tools dispose"
rule from Doc/absorption-framework-plan.md (Def. 4). If any of these regress, the
auditability claim of the architecture is broken, regardless of how well the
model behaves.

No network is required: every case asserted here is refused before the tool
reaches an external service.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

from agents.toolkit import TOOLS, execute_tool, tools_for_actor

CITIZEN = {"sub": "anon", "role": "citizen", "scopes": []}
OPERATOR = {"sub": "op@primarie.ro", "role": "operator",
            "scopes": ["case:read", "case:update"]}

_results: list[tuple[bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((cond, f"{name}{'' if cond else ': ' + detail}"))


async def main() -> int:
    # --- create_case: refuses an incomplete file -------------------------
    out = await execute_tool("create_case", {
        "procedure": "ci",
        "person": {"cnp": "1234567890123", "nume": "Popescu", "prenume": "Ion"},
        "provided": [],            # nothing uploaded
        "app_type": "CEI",
    }, CITIZEN)
    check("create_case refuses incomplete file",
          out.get("created") is False and out.get("error") == "incomplete_file", str(out))
    check("create_case reports what is missing",
          bool(out.get("missing")), str(out))

    # --- create_case: refuses missing person fields ----------------------
    out = await execute_tool("create_case", {
        "procedure": "ci",
        "person": {"nume": "Popescu"},          # no cnp/prenume
        "provided": ["carte_identitate"],
        "app_type": "CEI",
    }, CITIZEN)
    check("create_case refuses missing person fields",
          out.get("created") is False and out.get("error") == "missing_person_fields", str(out))

    # --- validate_document: deployment validity window (FS-0007) ---------
    old = (date.today() - timedelta(days=400)).isoformat()
    out = await execute_tool("validate_document",
                             {"kind": "dovada_adresa", "issued": old}, CITIZEN)
    check("validate_document rejects an out-of-date document",
          out.get("valid") is False and out.get("reason") == "doc_too_old", str(out))

    out = await execute_tool("validate_document", {"kind": "dovada_adresa"}, CITIZEN)
    check("validate_document requires an issue date where a window applies",
          out.get("valid") is False and out.get("reason") == "issue_date_required", str(out))

    fresh = (date.today() - timedelta(days=3)).isoformat()
    out = await execute_tool("validate_document",
                             {"kind": "dovada_adresa", "issued": fresh}, CITIZEN)
    check("validate_document accepts a recent document",
          out.get("valid") is True, str(out))

    out = await execute_tool("validate_document", {"kind": "nu_exista"}, CITIZEN)
    check("validate_document rejects an unknown document kind",
          out.get("valid") is False and out.get("reason") == "unknown_kind", str(out))

    # --- advance_case: status allowlist ----------------------------------
    out = await execute_tool("advance_case",
                             {"case_id": "CASE-1", "status": "APPROVED_BY_CHAT"}, OPERATOR)
    check("advance_case rejects a status outside the allowlist",
          out.get("error") == "invalid_status", str(out))

    # --- permission scopes ------------------------------------------------
    for name in ("list_tasks", "list_cases", "claim_task", "complete_task", "advance_case"):
        args = {"task_id": 1} if "task" in name else (
            {"case_id": "CASE-1", "status": "CLOSED"} if name == "advance_case" else {})
        out = await execute_tool(name, args, CITIZEN)
        check(f"{name} denies a citizen actor",
              out.get("error") == "forbidden", str(out))

    # --- tool visibility filtering ---------------------------------------
    citizen_tools = {t.name for t in tools_for_actor(CITIZEN)}
    operator_tools = {t.name for t in tools_for_actor(OPERATOR)}
    check("operator tools are hidden from citizens",
          not ({"list_tasks", "advance_case"} & citizen_tools), str(sorted(citizen_tools)))
    check("citizen tools remain available to operators",
          {"get_checklist", "create_case"} <= operator_tools, str(sorted(operator_tools)))
    check("every registered tool is reachable for some actor",
          set(TOOLS) == citizen_tools | operator_tools,
          str(set(TOOLS) - (citizen_tools | operator_tools)))

    # --- unknown tool is data, not a crash --------------------------------
    out = await execute_tool("rm_rf_everything", {}, OPERATOR)
    check("unknown tool returns a structured error",
          out.get("error") == "unknown_tool", str(out))

    passed = sum(1 for ok, _ in _results if ok)
    failed = len(_results) - passed
    for ok, label in _results:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nSummary: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
