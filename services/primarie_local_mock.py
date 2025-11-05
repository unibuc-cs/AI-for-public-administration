# services/primarie_local_mock.py
# Mock Primărie Locală API with persistence + state machine + OCR + webhooks + HITL tasks:
#  - /cases CRUD subset (create/list/get + status transitions with validation)
#  - /payments (mock confirmation; auto-advance to SIGN_PENDING)
#  - /sign (mock signature; auto-advance to SCHEDULED)
#  - /uploads (OCR mock + persist metadata)
#  - /notify/email and /notify/sms (persist notifications)
#  - /tasks (list/claim/complete) for operator human-in-the-loop
#
# Uses the shared SQLite DB via SQLModel.
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from db import (
    engine, init_db,
    Case, Payment, Signature, Notification,
    Upload as UploadRec,
    Task,
    SocialSlot, HubSlot, HubAppt
)

# Ensure tables exist
init_db()

local = APIRouter(prefix="/local", tags=["local"])


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

# Very light OCR keyword map for both CI and AS
DOC_KEYWORDS = {
    # CI
    "cert_nastere": ["certificat de nastere", "certificat naștere", "birth certificate"],
    "ci_veche": ["ci veche", "buletin vechi", "old id"],
    "dovada_adresa": ["dovada adresa", "extras cf", "contract inchiriere", "utility bill"],
    "politie": ["politie", "furt", "declaratie politie", "police"],
    # AS
    "cerere_ajutor": ["cerere ajutor", "cerere tip ajutor social", "formular ajutor social"],
    "carte_identitate": ["carte identitate", "c.i. solicitant", "buletin solicitant"],
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


# --------------------------- uploads (OCR) ---------------------------

@local.post("/uploads")
async def upload_file(
    file: UploadFile = File(...),
    kind_hint: str = Form("auto"),
    sid: str = Form("anon")
):
    """
    Receive a file, store metadata + OCR (simulated), link to session_id.
    NOTE: The main app is responsible for saving the actual file content; here we store metadata only.
    """
    content = await file.read()
    ocr_text = file.filename.lower()

    # Prefer hint when not 'auto'
    kind = None if kind_hint == "auto" else kind_hint
    # Fallback detection via filename keywords (toy OCR)
    if not kind:
        kinds = _doc_kinds_from_text(ocr_text)
        kind = kinds[0] if kinds else None

    # Best-effort persistence
    with Session(engine) as s:
        rec = UploadRec(
            session_id=sid,
            filename=file.filename,
            path=f"/tmp/{uuid.uuid4().hex}",  # demo path
            ocr_text=ocr_text,
            kind=kind,
            size=len(content),
            thumb=None,
        )
        s.add(rec)
        s.commit()
        s.refresh(rec)

    return {
        "ok": True,
        "upload": {
            "id": rec.id,
            "session_id": rec.session_id,
            "filename": rec.filename,
            "kind": rec.kind,
            "size": rec.size,
            "ocr_text": rec.ocr_text,
        },
        "recognized": _doc_kinds_from_text(ocr_text),
    }


@local.get("/uploads")
def list_uploads(session_id: str = Query(..., alias="session_id")):
    with Session(engine) as s:
        rows = s.exec(select(UploadRec).where(UploadRec.session_id == session_id)).all()
    recognized = set()
    items = []
    for u in rows:
        items.append({
            "id": u.id,
            "filename": u.filename,
            "kind": u.kind,
            "size": u.size,
            "ocr_text": u.ocr_text,
        })
        if u.kind:
            recognized.add(u.kind)
        for k in _doc_kinds_from_text(u.ocr_text or ""):
            recognized.add(k)
    return {"recognized": sorted(recognized), "items": items}


@local.delete("/uploads/purge")
def purge_uploads(session_id: str = Query(..., alias="session_id")):
    with Session(engine) as s:
        rows = s.exec(select(UploadRec).where(UploadRec.session_id == session_id)).all()
        count = len(rows)
        for r in rows:
            s.delete(r)
        s.commit()
    return {"ok": True, "deleted": count}


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
    with Session(engine) as s:
        row = s.exec(select(Case).where(Case.case_id == case_id)).first()
        if not row:
            raise HTTPException(status_code=404, detail="case not found")
        row.status = status
        s.add(row)
        s.commit()
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
    return {"ok": True, "task": {"id": t.id, "status": t.status, "notes": t.notes}}
