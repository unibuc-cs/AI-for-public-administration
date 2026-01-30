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



def _extract_person_fields_from_text(raw: str) -> dict:
    """Best-effort extraction of target form fields from OCR text.
    Keys: prenume, nume, cnp, adresa
    """
    t = (raw or "")
    if not t.strip():
        return {}
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln]
    low = "\n".join(lines).lower()
    out: dict = {}

    m = re.search(r"\b(\d{13})\b", low)
    if m:
        out["cnp"] = m.group(1)

    def after_kw(keyword: str):
        for i, ln in enumerate(lines):
            lnl = ln.lower()
            if keyword in lnl:
                idx = lnl.find(keyword) + len(keyword)
                val = ln[idx:].strip(" :-\t")
                if not val and i + 1 < len(lines):
                    val = lines[i+1].strip()
                return val
        return None

    v = after_kw("prenume")
    if v and len(v) >= 2:
        out.setdefault("prenume", v.title() if v.isupper() else v)
    v = after_kw("nume")
    if v and len(v) >= 2:
        # skip header-like lines
        if "last name" not in v.lower() and "nom" not in v.lower():
            out.setdefault("nume", v.title() if v.isupper() else v)

    if "prenume" not in out or "nume" not in out:
        v = after_kw("nume si prenume")
        if v and len(v.split()) >= 2:
            parts = v.split()
            out.setdefault("prenume", parts[0].title())
            out.setdefault("nume", " ".join(parts[1:]).title())

    addr = after_kw("domiciliu") or after_kw("adresa")
    if addr and len(addr) >= 5:
        out.setdefault("adresa", addr)
    else:
        for ln in lines:
            lnl = ln.lower()
            if (" str" in lnl or lnl.startswith("str") or "calea" in lnl or "bulevard" in lnl or "bd" in lnl):
                if len(ln) >= 8:
                    out.setdefault("adresa", ln)
                    break

    # remove empties
    out = {k: v for k, v in out.items() if isinstance(v, str) and v.strip()}
    return out


def _best_fields_from_uploads(sid: str) -> tuple[dict, list[str]]:
    """Return best-effort fields aggregated from latest uploads for this session."""
    if not sid:
        return {}, []

    # Get the latest uploads for this session using the database.
    with Session(engine) as ss:
        rows = ss.exec(
            select(Upload).where(Upload.session_id == sid).order_by(Upload.id.desc())
        ).all()
    fields: dict = {}
    sources: list[str] = []

    # A function to merge new fields into the main fields dict defined here.
    def merge(src: dict):
        for k, v in (src or {}).items():
            if not v:
                continue
            if k not in fields or not fields.get(k):
                fields[k] = v

    # Go through the latest 12 uploads and extract person fields from OCR text.
    for u in rows[:12]:
        kind = (u.kind or "").strip()
        # focus on CI veche and certificat nastere; but allow heuristic by OCR text too
        if kind in ("ci_veche", "cert_nastere") or (u.ocr_text and ("cnp" in (u.ocr_text.lower()))):
            f = _extract_person_fields_from_text(u.ocr_text or "")
            if f:
                merge(f)
                if kind:
                    sources.append(kind)

    # dedupe sources
    sources = list(dict.fromkeys([s for s in sources if s]))
    return fields, sources


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
    name = "ci"

    async def handle(self, state: AgentState) -> AgentState:
        app = state.get("app") or {}
        person = state.get("person") or {}
        msg = (state.get("message") or "").lower()
        sid = state.get("session_id") or ""

        # If we previously offered autofill and user answers yes/no, act here.
        if isinstance(app, dict) and app.get("pending_autofill_fields"):
            pending = app.get("pending_autofill_fields") or {}

            # Handle the positive case.
            if any(w in msg for w in ["da", "sigur", "ok", "yes", "completeaza", "completeaza", "aplica"]):
                # Emit a UI step to fill the form.
                state.setdefault("steps", []).append({"autofill": {"fields": pending}})
                app.pop("pending_autofill_fields", None)
                state["app"] = app
                state["reply"] = "Am completat campurile din formular cu datele detectate. Verifica te rog si corecteaza daca e nevoie."
                state["next_agent"] = None
                return state

            # Handle the negative case.
            if any(w in msg for w in ["nu", "no", "lasa", "manual"]):
                app.pop("pending_autofill_fields", None)
                state["app"] = app
                state["reply"] = "Ok, nu completez automat. Poti continua manual."
                state["next_agent"] = None
                return state


        # Make sure context is pinned when we are inside the CI form.
        if isinstance(app, dict):
            app.setdefault("ui_context", "ci")

        # Auto-run intake+OCR when uploads changed (no need for user to type anything).
        last_id = _get_last_upload_id(sid)
        if last_id is not None:
            seen = app.get("uploads_seen_last_id")
            if seen != last_id:
                app["uploads_seen_last_id"] = last_id
                state["app"] = app
                state["return_to"] = self.name
                state["next_agent"] = "doc_intake"
                state["reply"] = "Am detectat documente incarcate. Le analizez (OCR) si revin cu o propunere de completare automata."
                return state

        if last_id is not None and isinstance(app, dict):
            offered_for = app.get("autofill_offered_for_upload_id")
            if offered_for != last_id:
                fields, sources = _best_fields_from_uploads(sid)
                app["autofill_offered_for_upload_id"] = last_id # mark as offered for this upload id
                if fields:
                    app["pending_autofill_fields"] = fields
                    state["app"] = app

                    def fmt(k, label):
                        v = fields.get(k)
                        return f"{label}: {v}" if v else None

                    lines = [
                        fmt("prenume", "Prenume"),
                        fmt("nume", "Nume"),
                        fmt("cnp", "CNP"),
                        fmt("adresa", "Adresa"),
                    ]
                    lines = [x for x in lines if x]
                    src = ", ".join(sources) if sources else "documentele incarcate"

                    state["reply"] = (
                            f"Am analizat {src} si am gasit:\n"
                            + "\n".join(lines)
                            + "\n\nVrei sa completez automat aceste date in formular? (da/nu)"
                    )
                    state["next_agent"] = None
                    return state


        # Slot guidance (form-first UX):
        # On the CI form, the user must pick a slot in the UI selector to unlock the form.
        # We keep this simple: if no slot is selected yet, the assistant nudges the user to do so.
        # Then, once a slot is selected, the assistant proceeds with phase2: selecting application type and eligibility.
        selected_slot_id = app.get("selected_slot_id") if isinstance(app, dict) else None
        type_elig_confirmed = app.get("type_elig_confirmed") if isinstance(app, dict) else False
        app_type = app.get("type") if isinstance(app, dict) else None
        elig_reason = app.get("eligibility_reason") if isinstance(app, dict) else None

        # 0) Nudge to pick slot if none selected yet.
        if not selected_slot_id:
            # Only nudge when user is asking about scheduling or starting the flow.
            if (not msg) or any(k in msg for k in ["program", "programare", "slot", "programeaza", "vreau", "ajuta"]):
                state["reply"] = (
                    "Pentru CI, te rog mai intai sa alegi un interval din lista Slots (sus), apoi apasa Use this slot. "
                    "Dupa aceea pot verifica actele si te ghidez mai departe."
                )
                state["next_agent"] = None
                return state

        # 0.5) If selected but not phase2_ok:
        if selected_slot_id and not type_elig_confirmed:
            state["reply"] = (
                "Am retinut programarea. Acum, te rog alege Motiv si Tip cerere (Pasul 2)."
            )
            state["next_agent"] = None
            return state

        # 0.7) if Viza resedinta, VR, force eligibility_reason to CHANGE_ADDR:
        if app_type == "VR" and elig_reason != "CHANGE_ADDR":
            if isinstance(app, dict):
                app["eligibility_reason"] = "CHANGE_ADDR"
                state["app"] = app
            state["reply"] = "Pentru Viza resedinta, motivul trebuie sa fie Schimbare adresa/resedinta."
            state["next_agent"] = None
            return state

        # 1) If user indicates they uploaded docs, run intake+OCR.
        if any(k in msg for k in ["am incarcat", "am upload", "incarcat", "upload"]):
            state["return_to"] = self.name
            # Prevent re-triggering the auto-intake loop within the same request.
            last_id = _get_last_upload_id(sid)
            if last_id is not None and isinstance(app, dict):
                app["uploads_seen_last_id"] = last_id
                state["app"] = app
            state["next_agent"] = "doc_intake"
            state["reply"] = "Ok. Verific documentele incarcate si incerc sa completez automat ce pot."
            return state

        # 2) Require basic person fields.
        missing_fields = _missing_person_fields(person)
        if missing_fields:
            state.setdefault("steps", []).append({
                "missing_fields": missing_fields,
                "focus": missing_fields[0],
            })
            state["reply"] = "Pentru CI am nevoie de datele persoanei. Completeaza campurile marcate cu * (minim CNP, nume, prenume, email, telefon, adresa)."
            state["next_agent"] = None
            return state

        # 3) Decide application type (auto) from eligibility.
        elig_reason = (app.get("eligibility_reason") or CI_CFG.get("eligibility_reason") or "EXP_60")
        # elig = tool_eligibility(elig_reason)
        # if (app.get("type") or "auto") == "auto":
        #     app["type"] = elig["decided_type"]
        state.setdefault("steps", []).append({"eligibility": elig_reason, "type": app.get("type")})

        # 4) If no docs yet, ask user to upload (or say "am incarcat").
        docs = app.get("docs") or []
        if not isinstance(docs, list):
            docs = []
        app["docs"] = docs
        state["app"] = app

        missing_docs = tool_docs_missing(app["type"], app["eligibility_reason"], docs)["missing"]
        if missing_docs:
            state.setdefault("steps", []).append({"missing_docs": missing_docs})
            state["reply"] = "Lipsesc documente: " + ", ".join(missing_docs) + ". Incarca-le in pagina si apoi scrie: am incarcat documentele."
            state["next_agent"] = None
            return state

        # 5) Ready -> create case.
        state["reply"] = "Perfect. Am toate datele si documentele necesare. Creez cererea."
        state["next_agent"] = "case"
        return state
