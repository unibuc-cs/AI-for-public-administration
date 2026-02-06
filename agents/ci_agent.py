# agents/ci_agent.py
# Contextual wizard for the CI use case.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .base import Agent, AgentState
from .tools import tool_docs_missing



from db import engine, Upload
from sqlmodel import Session, select


CI_CFG = json.loads((Path(__file__).parent / "checklists" / "ci.json").read_text(encoding="utf-8"))


def _get_last_upload_id(sid: str) -> int | None:
    if not sid:
        return None
    with Session(engine) as ss:
        row = ss.exec(select(Upload.id).where(Upload.session_id == sid).order_by(Upload.id.desc())).first()
    return int(row) if row is not None else None



# def _extract_person_fields_from_text(raw: str) -> dict:
#     """Best-effort extraction of target form fields from OCR text.
#     Keys: prenume, nume, cnp, adresa
#     """
#     t = (raw or "")
#     if not t.strip():
#         return {}
#     lines = [re.sub(r"\s+", " ", ln).strip() for ln in t.splitlines()]
#     lines = [ln for ln in lines if ln]
#     low = "\n".join(lines).lower()
#     out: dict = {}
#
#     m = re.search(r"\b(\d{13})\b", low)
#     if m:
#         out["cnp"] = m.group(1)
#
#     def after_kw(keyword: str):
#         for i, ln in enumerate(lines):
#             lnl = ln.lower()
#             if keyword in lnl:
#                 idx = lnl.find(keyword) + len(keyword)
#                 val = ln[idx:].strip(" :-\t")
#                 if not val and i + 1 < len(lines):
#                     val = lines[i+1].strip()
#                 return val
#         return None
#
#     v = after_kw("prenume")
#     if v and len(v) >= 2:
#         out.setdefault("prenume", v.title() if v.isupper() else v)
#     v = after_kw("nume")
#     if v and len(v) >= 2:
#         # skip header-like lines
#         if "last name" not in v.lower() and "nom" not in v.lower():
#             out.setdefault("nume", v.title() if v.isupper() else v)
#
#     if "prenume" not in out or "nume" not in out:
#         v = after_kw("nume si prenume")
#         if v and len(v.split()) >= 2:
#             parts = v.split()
#             out.setdefault("prenume", parts[0].title())
#             out.setdefault("nume", " ".join(parts[1:]).title())
#
#     addr = after_kw("domiciliu") or after_kw("adresa")
#     if addr and len(addr) >= 5:
#         out.setdefault("adresa", addr)
#     else:
#         for ln in lines:
#             lnl = ln.lower()
#             if (" str" in lnl or lnl.startswith("str") or "calea" in lnl or "bulevard" in lnl or "bd" in lnl):
#                 if len(ln) >= 8:
#                     out.setdefault("adresa", ln)
#                     break
#
#     # remove empties
#     out = {k: v for k, v in out.items() if isinstance(v, str) and v.strip()}
#     return out
#
#
# def _best_fields_from_uploads(sid: str) -> tuple[dict, list[str]]:
#     """Return best-effort fields aggregated from latest uploads for this session."""
#     if not sid:
#         return {}, []
#
#     # Get the latest uploads for this session using the database.
#     with Session(engine) as ss:
#         rows = ss.exec(
#             select(Upload).where(Upload.session_id == sid).order_by(Upload.id.desc())
#         ).all()
#     fields: dict = {}
#     sources: list[str] = []
#
#     # A function to merge new fields into the main fields dict defined here.
#     def merge(src: dict):
#         for k, v in (src or {}).items():
#             if not v:
#                 continue
#             if k not in fields or not fields.get(k):
#                 fields[k] = v
#
#     # Go through the latest 12 uploads and extract person fields from OCR text.
#     for u in rows[:12]:
#         kind = (u.kind or "").strip()
#         # focus on CI veche and certificat nastere; but allow heuristic by OCR text too
#         if kind in ("ci_veche", "cert_nastere") or (u.ocr_text and ("cnp" in (u.ocr_text.lower()))):
#             f = _extract_person_fields_from_text(u.ocr_text or "")
#             if f:
#                 merge(f)
#                 if kind:
#                     sources.append(kind)
#
#     # dedupe sources
#     sources = list(dict.fromkeys([s for s in sources if s]))
#     return fields, sources


def _missing_person_fields(person: Dict[str, Any]) -> List[str]:
    # UI input ids: cnp, nume, prenume, email, telefon, adresa
    missing: List[str] = []
    if not (person.get("cnp") or "").strip():
        missing.append("cnp")
    if not (person.get("nume") or "").strip():
        missing.append("nume")
    if not (person.get("prenume") or "").strip():
        missing.append("prenume")
    if not (person.get("email") or "").strip():
        missing.append("email")
    if not (person.get("telefon") or "").strip():
        missing.append("telefon")
    # Keep address flat for the demo UI
    if not (person.get("adresa") or "").strip():
        missing.append("adresa")
    return missing

class CIAgent(Agent):
    name = "carte_identitate"

    # ---------- tiny helpers (keep simple) ----------

    # Replay with a text and next agent in graph
    def _reply(self, state: AgentState, text: str, next_agent: str | None = None) -> AgentState:
        state["reply"] = text
        state["next_agent"] = next_agent
        return state

    def _get_app(self, state: AgentState) -> dict:
        app = state.get("app") or {}
        if not isinstance(app, dict):
            app = {}
        app.setdefault("ui_context", "carte_identitate")
        state["app"] = app
        return app

    def _get_person(self, state: AgentState) -> dict:
        person = state.get("person") or {}
        if not isinstance(person, dict):
            person = {}
        state["person"] = person
        return person

    def _msg(self, state: AgentState) -> str:
        return (state.get("message") or "").strip().lower()

    def _sid(self, state: AgentState) -> str:
        return (state.get("session_id") or "").strip()

    def _selected_slot(self, app: dict) -> str | None:
        v = app.get("selected_slot_id")
        return v if isinstance(v, str) and v.strip() else None

    def _type_elig_confirmed(self, app: dict) -> bool:
        return bool(app.get("type_elig_confirmed"))

    def _app_type(self, app: dict) -> str | None:
        v = app.get("type")
        return v if isinstance(v, str) and v.strip() else None

    def _elig_reason(self, app: dict) -> str | None:
        v = app.get("eligibility_reason")
        return v if isinstance(v, str) and v.strip() else None

    # ---------- handlers ----------

    def _maybe_run_doc_intake_on_new_upload(self, state: AgentState, app: dict, sid: str) -> AgentState | None:
        last_id = _get_last_upload_id(sid)
        if last_id is None:
            return None

        seen = app.get("uploads_seen_last_id")
        if seen == last_id:
            return None

        app["uploads_seen_last_id"] = last_id
        state["app"] = app
        state["return_to"] = self.name
        state["next_agent"] = "doc_intake"

        # Disabled the reply text to reduce clutter, since the doc_intake agent will provide its own reply.
        state["reply"] = "" #"Am detectat documente incarcate. Le analizez (OCR) si revin."
        return state
    #
    # def _maybe_offer_autofill(self, state: AgentState, app: dict, sid: str) -> AgentState | None:
    #     last_id = _get_last_upload_id(sid)
    #     if last_id is None:
    #         return None
    #
    #     offered_for = app.get("autofill_offered_for_upload_id")
    #     if offered_for == last_id:
    #         return None
    #
    #     fields, sources = _best_fields_from_uploads(sid)
    #     app["autofill_offered_for_upload_id"] = last_id
    #     state["app"] = app
    #
    #     if not fields:
    #         return None
    #
    #     app["pending_autofill_fields"] = fields
    #     state["app"] = app
    #
    #     def fmt(k: str, label: str) -> str | None:
    #         v = fields.get(k)
    #         return f"{label}: {v}" if v else None
    #
    #     lines = [fmt("prenume", "Prenume"), fmt("nume", "Nume"), fmt("cnp", "CNP"), fmt("adresa", "Adresa")]
    #     lines = [x for x in lines if x]
    #     src = ", ".join(sources) if sources else "documentele incarcate"
    #
    #     return self._reply(
    #         state,
    #         "Am analizat " + src + " si am gasit:\n"
    #         + "\n".join(lines)
    #         + "\n\nVrei sa completez automat aceste date in formular? (da/nu)"
    #     )

    def _wizard_step_reply(self, state: AgentState, app: dict, sid: str, msg: str) -> AgentState | None:
        slot = self._selected_slot(app)
        if not slot:
            return self._reply(state, "Step 1/3: Select a slot from Slots (top), then click Use this slot.")

        if "__phase1_done__" in msg and not self._type_elig_confirmed(app):
            if app.get("last_wizard_step", None) != "slot_selected":
                app["last_wizard_step"] = "slot_selected"
                state["app"] = app

            return self._reply(state, "Step 2/3: Slot is set. Now select Motiv (eligibility) and Tip cerere.")

        # VR rule (simple enforcement)
        if self._app_type(app) == "VR" and self._elig_reason(app) != "CHANGE_ADDR":
            app["eligibility_reason"] = "CHANGE_ADDR"
            state["app"] = app
            return self._reply(state, "For VR, Motiv must be CHANGE_ADDR. I set it for you.")

        # after phase2 done, give clear instruction
        if "__phase2_done__" in msg:
            if app.get("last_wizard_step", None) != "phase_prefill":
                app["last_wizard_step"] = "phase_prefill"
                state["app"] = app
                return self._reply(
                    state,
                    "Step 3/3: Optional prefill: upload ci_veche or cert_nastere to prefill fields via OCR. "
                    "If you skip, fill the fields manually. Then upload required docs and click Validate."
                )

        # Step 3 gating: keep it light; only nudge if no prefill docs yet
        docs = app.get("docs") or []
        if not isinstance(docs, list):
            docs = []
        kinds = {(d.get("kind") or "") for d in docs if isinstance(d, dict)}
        has_prefill = ("ci_veche" in kinds) or ("cert_nastere" in kinds)

        if not has_prefill:
            # DB fallback (simple)
            with Session(engine) as ss:
                rows = ss.exec(select(Upload.kind).where(Upload.session_id == sid)).all()
            kinds_db = {(k or "").strip() for k in rows}
            has_prefill = ("ci_veche" in kinds_db) or ("cert_nastere" in kinds_db)

        if not has_prefill:
            return self._reply(
                state,
                f"Step 3/3: Optional prefill: upload ci_veche or cert_nastere to prefill fields via OCR. "
                "If you skip, fill the fields manually. Then upload required docs and click Validate."
            )

        return None

    # ---------- main handle ----------
    async def handle(self, state: AgentState) -> AgentState:
        app = self._get_app(state)
        person = self._get_person(state)
        msg = self._msg(state)
        sid = self._sid(state)

        # 2) Detect new uploads and run doc_intake (do not require slot for OCR)
        out = self._maybe_run_doc_intake_on_new_upload(state, app, sid)
        if out:
            return out

        # 3) Wizard guidance (slot -> type/elig -> step3 suggestion)
        out = self._wizard_step_reply(state, app, sid, msg)
        if out:
            return out

        # 4) Missing person fields (after step3)
        missing_fields = _missing_person_fields(person)
        if missing_fields:
            state.setdefault("steps", []).append({"type":"toast","payload":{"level":"warn","title":"Date lipsa","message":"Completeaza campurile lipsa."}})
            state.setdefault("steps", []).append({"type":"focus_field","payload":{"field_id": missing_fields[0]}})
            return self._reply(state, "Please fill required fields.")

        # 5) Missing docs
        docs = app.get("docs") or []
        if not isinstance(docs, list):
            docs = []
        app["docs"] = docs
        state["app"] = app

        missing_docs = tool_docs_missing(app.get("type"), app.get("eligibility_reason"), docs)["missing"]
        if missing_docs:
            state.setdefault("steps", []).append({"type":"highlight_missing_docs","payload":{"kinds": missing_docs}})
            state.setdefault("steps", []).append({"type":"open_section","payload":{"section_id":"slotsBox"}})
            return self._reply(state,
                               "Missing documents: " + ", ".join(missing_docs) + ". Upload them then click Validate.")

        # 6) Ready
        return self._reply(state, "All good. You can click Validate to continue.")
