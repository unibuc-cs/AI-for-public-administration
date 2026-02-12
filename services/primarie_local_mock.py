# services/primarie_local_mock.py
# Mock Primarie Locala API with persistence + state machine + OCR + webhooks + HITL tasks:
#  - /cases CRUD subset (create/list/get + status transitions with validation)
#  - /payments (mock confirmation; auto-advance to SIGN_PENDING)
#  - /sign (mock signature; auto-advance to SCHEDULED)
#  - /uploads (OCR mock + persist metadata)
#  - /notify/email and /notify/sms (persist notifications)
#  - /tasks (list/claim/complete) for operator human-in-the-loop
#
# Uses the shared SQLite DB via SQLModel.
from __future__ import annotations
from fastapi import Request, Response
import json
import os
import io
import re
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query, FastAPI
from fastapi.responses import JSONResponse
from sqlmodel import Session, select


from db import (
    engine, init_db,
    Case, Payment, Signature, Notification,
    Upload as UploadRec,
    Task,
    SocialSlot, HubSlot, HubAppt,
    AuditLog,
)

from .ocr_utils import extract_person_fields, validate_person_simple

# Ensure tables exist
init_db()


# --- OCR helpers (prototype-friendly, local-first) ---
# We keep OCR optional: if the OCR library is not installed, we fall back to filename-based detection.
# Recommended for local runs:
#   pip install easyocr opencv-python-headless pillow
# (easyocr pulls torch; on CPU this is still OK for a prototype.)
_OCR_READER = None

def _get_easyocr_reader():
    global _OCR_READER
    if _OCR_READER is not None:
        return _OCR_READER
    try:
        import easyocr  # type: ignore
        # Romanian isn't always a separate model in easyocr; 'en' covers Latin well, 'ro' may be supported depending on version.
        # We include both, and easyocr will ignore unsupported ones.
        _OCR_READER = easyocr.Reader(['ro', 'en'], gpu=False)
        return _OCR_READER
    except Exception:
        return None

def _ocr_text_from_bytes(content: bytes) -> str:
    """Return raw OCR text from image bytes, best-effort."""
    reader = _get_easyocr_reader()
    if reader is None:
        return ""

    try:
        from PIL import Image
        import numpy as np  # type: ignore

        im = Image.open(io.BytesIO(content)).convert("RGB")
        # Mild resize to help OCR on small photos; keep it simple.
        w, h = im.size
        if max(w, h) < 1200:
            scale = 1200 / max(w, h)
            im = im.resize((int(w*scale), int(h*scale)))

        arr = np.array(im)
        out = reader.readtext(arr, detail=0, paragraph=True)
        if isinstance(out, list):
            return "\n".join([str(x) for x in out if x])
        return str(out)
    except Exception:
        print(traceback.format_exc())
        return ""
        

def _extract_person_fields_from_text(raw: str) -> dict:
    # Backwards compatible wrapper used by existing endpoints.
    return extract_person_fields(raw or "")


local = APIRouter(tags=["local"])


# --------------------------- helpers ---------------------------

def _now_iso() -> str:
    return datetime.utcnow().isoformat()

def _gen_case_id(prefix="CASE") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

def _read_json(txt: Optional[str]) -> Dict[str, Any]:
    if not txt:
        return {}
    try:
        return json.loads(txt)
    except Exception:
        return {}

def _write_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)

def _infer_program_from_application(app: Dict[str, Any]) -> str:
    # when creating a case we allow either "type" or "program" to indicate channel
    # CI flow uses "type" (CEI/CIS/CIP), AS flow uses "program":"AS"
    if "program" in app and app["program"]:
        return str(app["program"])
    if "type" in app and app["type"]:
        return str(app["type"])
    return "UNKNOWN"


def _audit(actor: str, action: str, entity_type: str = "", entity_id: str = "", details: Any = None) -> None:
    """Minimal audit logging for operator-facing traceability (prototype level)."""
    try:
        with Session(engine) as s:
            s.add(AuditLog(
                actor=actor or "system",
                action=action,
                entity_type=entity_type or "",
                entity_id=entity_id or "",
                details_json=_write_json(details or {}),
            ))
            s.commit()
    except Exception:
        # Never break the demo because audit failed.
        pass

# Very light OCR keyword map for both CI and AS
DOC_KEYWORDS = {
    # CI
    "cert_nastere": ["certificat de nastere", "certificat nastere", "birth certificate"],
    # Use one canonical id for ID docs across flows
    "carte_identitate": [
        "carte identitate", "c.i. solicitant", "buletin", "buletin solicitant",
        "ci veche", "buletin vechi", "old id"
    ],
    "dovada_adresa": ["dovada adresa", "extras cf", "contract inchiriere", "utility bill"],
    "politie": ["politie", "furt", "declaratie politie", "police"],
    # AS
    "cerere_ajutor": ["cerere ajutor", "cerere tip ajutor social", "formular ajutor social"],
    "acte_venit": ["adeverinta venit", "cupon pensie", "venit", "salariu"],
    "acte_locuire": ["contract inchiriere", "dovada locuire", "adeverinta spatiu"],
    "acte_familie": ["certificat casatorie", "certificate copii", "nastere copil"],
    "cont_bancar": ["iban", "extras cont", "cont bancar"],
}

def _doc_kinds_from_text(text: str) -> List[str]:
    t = (text or "").lower()
    found = []
    for kind, kws in DOC_KEYWORDS.items():
        if any(kw in t for kw in kws):
            found.append(kind)
    return list(sorted(set(found)))

@local.get("/")
def local_root():
    return {"ok": True,
            "message": "Hello primarie messa"}

# --------------------------- uploads (OCR) ---------------------------


@local.post("/uploads")
async def upload_file(
    file: UploadFile = File(...),
    docHint: str = Form("auto"),
    sid: str = Form("anon")
):
    """
    Stateless OCR mock:
    - Does NOT persist uploads.
    - Returns OCR text + detected kind + recognized kinds.
    Main app owns DB persistence and override.
    """

    # Read file content and perform OCR
    content = await file.read()
    ocr_text = _ocr_text_from_bytes(content) or file.filename.lower()

    # Prefer hint given by user when not 'auto'
    kind = None if docHint == "auto" else docHint

    # Fallback detection via filename keywords (toy OCR)
    if not kind:
        kinds = _doc_kinds_from_text(ocr_text)
        kind = kinds[0] if kinds else None

    recognized = _doc_kinds_from_text(ocr_text)

    # Optional audit (no DB id)
    try:
        _audit(
            actor="system",
            action="UPLOAD_OCR",
            entity_type="upload",
            entity_id="mock",
            details={
                "session_id": sid,
                "filename": file.filename,
                "kind": kind,
                "size": len(content),
            },
        )
    except Exception:
        pass

    return {
        "ok": True,
        "upload": {
            "id": "mock",
            "session_id": sid,
            "filename": file.filename,
            "kind": kind,
            "size": len(content),
            "ocr_text": ocr_text,
        },
        "recognized": recognized,
    }


@local.delete("/uploads/purge")
def purge_uploads(session_id: str = Query(..., alias="session_id")):
    # Stateless mock: nothing to purge here
    return {"ok": True, "session_id": session_id}

# --------------------------- social slots (AS) ---------------------------
def _seed_social_slots():
    with Session(engine) as s:
        has_any = s.exec(select(SocialSlot)).first()
        if has_any:
            return
        base = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        rows = []
        for i in range(6):
            rows.append(SocialSlot(id=f"AS-{i+1}", location_id="Bucuresti-S1",
                                   when=base + timedelta(days=i, hours=9)))
            rows.append(SocialSlot(id=f"AS-{i+7}", location_id="Ilfov-01",
                                   when=base + timedelta(days=i, hours=11)))
        for r in rows:
            s.add(r)
        s.commit()

_seed_social_slots()


@local.get("/slots-social", response_model=List[SocialSlot])
def list_social_slots(location_id: Optional[str] = None):
    with Session(engine) as s:
        stmt = select(SocialSlot)
        if location_id:
            stmt = stmt.where(SocialSlot.location_id == location_id)
        rows = s.exec(stmt).all()
    return [{"id": r.id, "location_id": r.location_id, "when": r.when.isoformat()} for r in rows]


@local.post("/reserve-social")
def reserve_social(payload: Dict[str, Any]):
    slot_id = payload.get("slot_id")
    cnp = payload.get("cnp") or "anon"
    with Session(engine) as s:
        slot = s.get(SocialSlot, slot_id)
        if not slot:
            raise HTTPException(status_code=404, detail="slot not found")
    appt = {
        "appt_id": f"id_{cnp}_as",
        "slot_id": slot_id,
        "when": slot.when.isoformat(),
        "location_id": slot.location_id,
    }
    return {"via": "LOCAL", "appointment": appt}


# --------------------------- cases ---------------------------
@local.post("/cases")
def create_case(payload: Dict[str, Any]):
    """
    Create a Case that matches db.py:
      - case_id: public id
      - type: application type or program (e.g., CEI/CIS/CIP or AS)
      - status: NEW
      - person_json / payload_json: raw JSON strings for flexibility
    Expected payload: { "person": {...}, "application": {...} }
    """
    person = payload.get("person") or {}
    app = payload.get("application") or {}

    # Minimal validation (prototype).
    errs = validate_person_simple(person)
    if errs:
        raise HTTPException(status_code=400, detail={"errors": errs})
    program_or_type = _infer_program_from_application(app)

    case_id = _gen_case_id(prefix="CASE")
    row = Case(
        case_id=case_id,
        type=program_or_type,
        status="NEW",
        person_json=_write_json(person),
        payload_json=_write_json(app),
    )
    with Session(engine) as s:
        s.add(row)
        s.commit()
        s.refresh(row)

    _audit(actor="system", action="CASE_CREATE", entity_type="case", entity_id=row.case_id, details={
        "type": row.type,
        "status": row.status,
    })

    return {
        "case_id": row.case_id,
        "type": row.type,
        "status": row.status,
        "person": person,
        "application": app,
        "created_at": _now_iso(),
    }


@local.get("/cases")
def list_cases(type: Optional[str] = None):
    with Session(engine) as s:
        rows = s.exec(select(Case)).all()
    out = []
    for r in rows:
        pj = _read_json(r.person_json)
        aj = _read_json(r.payload_json)
        if type and r.type != type:
            continue
        out.append({
            "case_id": r.case_id,
            "type": r.type,
            "status": r.status,
            "person": pj,
            "application": aj,
        })
    return out


@local.patch("/cases/{case_id}")
def update_case_status(case_id: str, status: str = Query(...)):
    # Hard allowlist for demo safety & predictable operator UX.
    allowed = {"NEW","SCHEDULED","IN_PROCESS","READY_FOR_PICKUP","CLOSED"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"invalid status: {status}")
    with Session(engine) as s:
        row = s.exec(select(Case).where(Case.case_id == case_id)).first()
        if not row:
            raise HTTPException(status_code=404, detail="case not found")
        row.status = status
        s.add(row)
        s.commit()

    _audit(actor="system", action="CASE_STATUS_UPDATE", entity_type="case", entity_id=case_id, details={
        "new_status": status,
    })
    return {"ok": True, "case_id": case_id, "status": status}

# --------------------------- tasks (HITL) ---------------------------
@local.get("/tasks")
def list_tasks(type: Optional[str] = None, status: Optional[str] = None):
    """
    Since Task doesn't carry `type` in db.py, we infer it by looking up the Case by `case_id`.
    """
    with Session(engine) as s:
        tasks = s.exec(select(Task)).all()
        out = []
        for t in tasks:
            c = s.exec(select(Case).where(Case.case_id == t.case_id)).first()
            c_type = c.type if c else None
            if status and t.status != status:
                continue
            if type and c_type != type:
                continue
            out.append({
                "id": t.id,
                "kind": t.kind,
                "status": t.status,
                "assignee": t.assignee,
                "notes": t.notes,
                "case_id": t.case_id,
                "case_type": c_type,
            })
    return out


@local.post("/tasks/{task_id}/claim")
def claim_task(task_id: int, payload: Dict[str, Any]):
    assignee = payload.get("assignee") or "operator@demo.local"
    with Session(engine) as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="task not found")
        t.status = "ASSIGNED"
        t.assignee = assignee
        s.add(t)
        s.commit()
        s.refresh(t)

    _audit(actor=assignee, action="TASK_CLAIM", entity_type="task", entity_id=str(task_id), details={
        "case_id": t.case_id,
        "kind": t.kind,
    })
    return {"ok": True, "task": {"id": t.id, "status": t.status, "assignee": t.assignee}}


@local.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, payload: Dict[str, Any]):
    notes = payload.get("notes")
    with Session(engine) as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(status_code=404, detail="task not found")
        t.status = "DONE"
        t.notes = notes
        s.add(t)
        s.commit()
        s.refresh(t)

    _audit(actor=str(t.assignee or "operator@demo.local"), action="TASK_COMPLETE", entity_type="task", entity_id=str(task_id), details={
        "case_id": t.case_id,
        "kind": t.kind,
    })
    return {"ok": True, "task": {"id": t.id, "status": t.status, "notes": t.notes}}


@local.get("/audit")
def list_audit(limit: int = 100):
    """Return latest audit entries (prototype debug endpoint)."""
    limit = max(1, min(int(limit or 100), 500))
    with Session(engine) as s:
        rows = s.exec(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "actor": r.actor,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "details": _read_json(r.details_json),
        })
    return out

app = FastAPI(title="Primarie local mock")
app.include_router(local)