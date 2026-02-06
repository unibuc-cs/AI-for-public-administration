# agents/doc_intake_agent.py
#
# Document intake agent:
# - Reads uploaded files for the current session from the main DB.
# - Normalizes the detected doc kinds to allowed identifiers.
# - Updates app['docs'] (idempotent upsert by doc kind).
# - Chains into DocOCRAgent to auto-fill fields from OCR text.
#
# Policy: "Always override latest". If the same doc kind appears multiple times,
# we keep a single entry in app['docs'] and treat it as present.

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from sqlmodel import Session, select

from db import engine, Upload
from .base import Agent, AgentState
from .identifiers import allowed_all_doc_ids
from .settings import LLM_USE
from .llm_utils import normalize_doc_id_with_llm, get_domain_from_ui_context


def _upsert_doc(docs: List[Dict[str, Any]], kind: str) -> None:
    if not kind:
        return
    for d in docs:
        if (d.get("kind") or "") == kind:
            d["status"] = "ok"
            return
    docs.append({"kind": kind, "status": "ok"})



class DocIntakeAgent(Agent):
    name = "doc_intake"

    def _load_uploads(self, sid: str) -> List[Dict[str, Any]]:
        with Session(engine) as s:
            rows = s.exec(select(Upload).where(Upload.session_id == sid).order_by(Upload.id)).all()
        items: List[Dict[str, Any]] = []
        for u in rows:
            items.append({
                "id": u.id,
                "filename": u.filename,
                "kind": u.kind,
                "ocr_text": u.ocr_text,
                "path": u.path,
                "thumb": u.thumb,
            })
        return items

    def _guess_kind(self, it: Dict[str, Any]) -> str:
        fn = (it.get("filename") or "").lower()
        txt = (it.get("ocr_text") or "").lower()

        # Identity card (CI)
        if ("carte" in txt and "identitate" in txt) or ("cnp" in txt and "seria" in txt):
            return "ci_veche"
        if "carte_identitate" in fn or "buletin" in fn:
            return "ci_veche"

        # Birth certificate
        if ("certificat" in txt and "naster" in txt) or ("certificat de nastere" in txt):
            return "cert_nastere"
        if "nastere" in fn or "certificat" in fn:
            return "cert_nastere"

        # Address proof (generic heuristic)
        if ("domiciliu" in txt and "adresa" in txt) or ("resedinta" in txt and "adresa" in txt):
            return "dovada_adresa"
        if ("dovada" in fn and "adresa" in fn) or ("resedinta" in fn):
            return "dovada_adresa"

        return ""

    async def _normalize_kind(self, raw: str, allowed: Set[str]) -> Optional[str]:
        r = (raw or "").strip().lower()
        if not r:
            return None
        if r in allowed:
            return r
        if not LLM_USE:
            return None

        try:
            out = await normalize_doc_id_with_llm(r, sorted(allowed))
            cand = (out.get("doc_id") or "").strip().lower()
            return cand if cand in allowed else None
        except Exception:
            return None

    async def handle(self, state: AgentState) -> AgentState:
        sid = state.get("session_id") or ""
        app = state.get("app") or {}


        # Load allowed doc IDs
        allowed = set(allowed_all_doc_ids())

        # Load the uploads for this session from the DB
        items = self._load_uploads(sid)
        # if no uploads, just return
        if not items:
            state["next_agent"] = state.get("return_to", "entry")
            return state


        recognized: List[str] = []

        # Process each upload and try to recognize its kind
        #---------
        for it in items:
            raw_kind = it.get("kind")
            if not raw_kind or raw_kind == "auto":
                raw_kind = self._guess_kind(it)

            norm = await self._normalize_kind(raw_kind, allowed)
            if norm:
                recognized.append(norm)

        # De-duplicate while preserving order
        seen: Set[str] = set()
        recognized_uniq: List[str] = []
        for k in recognized:
            if k not in seen:
                seen.add(k)
                recognized_uniq.append(k)
        #---------


        # Update app['docs'] with recognized document kinds
        docs = app.get("docs") or []
        if not isinstance(docs, list):
            docs = []

        for k in recognized_uniq:
            _upsert_doc(docs, k)

        app["docs"] = docs
        state["app"] = app

        # Chain into the OCR agent to extract fields from the recognized documents.
        state["next_agent"] = "doc_ocr"

        # Sets the step for next agents about the upload results
        msg = ""
        if recognized_uniq:
            msg = "Recognized: " + ", ".join(recognized_uniq) + "."
        else:
            msg = "Could not recognize document kind. Try a clearer image or rename the file."
        state.setdefault("steps", []).append({
            "type": "toast",
            "payload": {
                "level": "info" if recognized_uniq else "warn",
                "title": "Upload",
                "message": msg
            }
        })

        # user face feedback for recognized docs
        state["reply"] = msg


        # Ensure return_to is set to the current UI context if not already present
        if "return_to" not in state:
            app = state.get("app") or {}
            state["return_to"] = get_domain_from_ui_context(app.get("ui_context"))
        return state
