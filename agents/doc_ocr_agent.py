# agents/doc_ocr_agent.py
# Extract structured entities from uploaded document OCR text and store them on Upload rows.
# Policy:
# - Main app persists uploads.
# - This agent updates Upload.extracted_json/status/updated_at.
# - It proposes autofill values in chat, but applies them ONLY after user confirmation (YES/NO).

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List

from sqlmodel import Session, select

from db import engine, Upload
from .base import Agent, AgentState
from services.ocr_utils import extract_entities

# Helper to format extracted fields for chat preview
def _format_fields(fields: dict) -> str:
    lines = []
    for k, v in (fields or {}).items():
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        lines.append(f"- {k}: {s}")
    return "\n".join(lines)

class DocOCRAgent(Agent):
    name = "doc_ocr"

    async def handle(self, state: AgentState) -> AgentState:
        sid = state.get("session_id") or ""
        if not sid:
            state["next_agent"] = state.pop("return_to", None)
            return state

        merged_fields: Dict[str, str] = {}
        with Session(engine) as ss:
            uploads: List[Upload] = ss.exec(
                select(Upload).where(Upload.session_id == sid).order_by(Upload.id)
            ).all()

            for up in uploads:
                raw = (up.ocr_text or "").strip()
                if not raw:
                    continue

                # Extract fields from OCR text and update DB record
                entities = extract_entities(raw)
                up.extracted_json = json.dumps(entities, ensure_ascii=False)
                up.updated_at = datetime.utcnow()

                # Merge person fields into overall extracted fields, with "latest wins" policy across multiple uploads
                person_fields = entities.get("person") if isinstance(entities, dict) else {}
                if isinstance(person_fields, dict) and any(v for v in person_fields.values()):
                    up.status = "ok"
                    # newest wins
                    for k, v in person_fields.items():
                        if v:
                            merged_fields[k] = v
                else:
                    up.status = "needs_review"


            ss.commit()

        # Store pending autofill values in app (router will confirm and UI will apply)
        app = state.get("app") if isinstance(state.get("app"), dict) else {}
        app["pending_autofill_fields"] = merged_fields
        app["pending_autofill_offer"] = bool(merged_fields)
        state["app"] = app

        # typed UI step to set fields and focus on the first one
        steps = state.setdefault("steps", [])
        steps.append({
            "type":"toast",
            "payload" : {
                "level" : "info",
                "title" : "OCR",
                "message" : "OCR entities updated for uploaded documents"
            }
        })

        # Build a reasonable preview for chat and ask user confirmation
        if merged_fields:
            preview = _format_fields(merged_fields)
            state["reply"] = (
                "Am extras urmatoarele campuri din documente:\n"
                f"{preview}\n\n"
                "Vrei sa le completez automat in formular? Raspunde DA sau NU."
            )

            # Mark a pending confirmation flag so router can intercept the YES/NO answer
            app["pending_autofill_offer"] = True
            state["app"] = app
        else:
            state["reply"] = "OCR processed, but I did not find usable fields. You can try "

        state["reply"] = "OCR processed. I can suggest autofill values if you want"
        state["next_agent"] = state.pop("return_to", None)
        return state












