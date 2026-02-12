# agents/tools.py
# A lightweight set of "MCP-like" tools the orchestrator can call.
# Each tool encapsulates a clear external side-effect or query:
#   - Eligibility mapping (auto decide CEI/CIS/CIP/)
#   - Document requirement / missing detection
#   - Case submission to Primarie Locala
#   - Payment & Signature
#   - Scheduling via CEI-HUB (and local fallback)
#   - Reschedule/Cancel appointments
#   - File upload to OCR mock
#   - Notifications (email/SMS) via webhooks
#
# The orchestrator coordinates these tools in a consistent flow.

import os, json
from pathlib import Path
import httpx
from sympy.multipledispatch.dispatcher import RaiseNotImplementedError
from .identifiers import docs_as_cards
from agents.http_client import make_async_client

# External service endpoints (mock servers)
RUN_MODE = os.getenv("RUN_MODE", "mounted").lower()  # "mounted" | "split"
_default_hub = "http://localhost:8000/hub" if RUN_MODE == "mounted" else "http://localhost:8001"
_default_local = "http://localhost:8000/local" if RUN_MODE == "mounted" else "http://localhost:8002"
HUB_URL = os.getenv("HUB_URL", _default_hub)
LOCAL_URL = os.getenv("LOCAL_URL", _default_local)


# External service endpoints (mock servers)


# --------------------------- ELIGIBILITY & DOCS ---------------------------


_CHECKLIST_DIR = Path(__file__).parent / "checklists"


def _load_checklist(name: str) -> dict:
    p = _CHECKLIST_DIR / f"{name}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def tool_docs_required(program: str, app_type: str | None = None, elig_reason: str | None = None) -> dict:
    """Return required document ids.

    Design:
    - CI uses a structured checklist: common_docs + types + eligibility_docs.
    - Social/Taxe can use a simple top-level required_docs.
    """
    required: set[str] = set()
    prog = (program or "").strip().lower()

    if prog in {"ci", "carte_identitate"}:
        cfg = _load_checklist("ci")
        for d in (cfg.get("common_docs") or []):
            if isinstance(d, str) and d:
                required.add(d)
        t = (app_type or "").strip().upper()
        if t:
            spec = (cfg.get("types") or {}).get(t) or {}
            for d in (spec.get("required_docs") or []):
                if isinstance(d, str) and d:
                    required.add(d)
        r = (elig_reason or "").strip().upper()
        if r:
            for d in ((cfg.get("eligibility_docs") or {}).get(r) or []):
                if isinstance(d, str) and d:
                    required.add(d)
        return {"required": sorted(required)}

    # Social aid (ajutor social)
    if prog in {"as", "social"}:
        cfg = _load_checklist("social")
        for d in (cfg.get("required_docs") or []):
            if isinstance(d, str) and d:
                required.add(d)
        return {"required": sorted(required)}

    # Taxes (3rd demo use case)
    if prog in {"taxe"}:
        cfg = _load_checklist("taxe")
        for d in (cfg.get("required_docs") or []):
            if isinstance(d, str) and d:
                required.add(d)
        return {"required": sorted(required)}

    required_list = sorted(required)
    return {"required": required_list, "required_cards": docs_as_cards(required_list)}


def tool_docs_missing(program: str, app_type: str | None, eligibility_reason: str | None, docs: list[dict]) -> dict:
    """
    Compare required documents vs. those provided and return the missing ones.
    """
    required = set(tool_docs_required(program, app_type=app_type, elig_reason=eligibility_reason)["required"])
    provided = {d["kind"] for d in docs if d.get("status") == "ok"}
    missing_list = sorted(list(required - provided))
    return {"missing": missing_list, "missing_cards": docs_as_cards(missing_list)}


# --------------------------- CASE SUBMISSION ---------------------------

async def tool_case_submit(person: dict, app: dict) -> dict:
    """
    Create a new case via the Primarie Locala mock service.
    Expects {"person": {...}, "application": {...}} so primarie_local_mock can infer program/type.
    For CI: app should contain "type": "CEI"/"CIS"/"VR" and optionally "docs".
    For AS: app should contain "program": "AS" and "docs".
    """
    payload = {
        "person": person or {},
        "application": app or {}
    }
    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/cases", json=payload)
        r.raise_for_status()
        return r.json()


# --------------------------- PAYMENT & SIGNATURE ---------------------------

async def tool_payment(case_id: str, amount: float) -> dict:
    try:
        async with make_async_client() as client:
            r = await client.post(f"{LOCAL_URL}/payments", json={"case_id": case_id, "amount": amount})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"skipped": True, "reason": f"payments endpoint missing: {e}"}

async def tool_signature(case_id: str) -> dict:
    try:
        async with make_async_client() as client:
            r = await client.post(f"{LOCAL_URL}/sign", json={"case_id": case_id})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"skipped": True, "reason": f"signature endpoint missing: {e}"}

# --------------------------- SCHEDULING ---------------------------

async def tool_schedule(app_type: str,
                        location_id: str="Bucuresti-S1",
                        cnp: str | None = None) -> dict:
    """
    If the application type is CEI, fetch slot list and schedule the first available slot.
    Otherwise, return a "local" placeholder appointment for CIS/CIP.
    """
    async with make_async_client() as client:
        if app_type == "CEI":
            slots = (await client.get(f"{HUB_URL}/slots", params={"location_id":location_id})).json()
            if not slots:
                return {"via":"HUB","error":"no_slots"}
            s0 = slots[0]
            appt = (await client.post(f"{HUB_URL}/appointments",
                                      json={"person": {}, "docs_ok": True,
                                            "slot_id": s0["id"], "cnp": cnp if cnp else None
                                            })).json()
            return {"via":"HUB", "slot": s0, "appointment": appt}
        else:
            # Local mock scheduling for CIS/CIP
            return {"via":"LOCAL", "appointment": {"appt_id":"local-na","when":"soon","location_id":"Primarie-01"}}


async def tool_schedule_social_by_slot(slot_id: str, cnp: str | None = None):
    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/reserve-social", json={"slot_id": slot_id, "cnp": cnp})
        r.raise_for_status()
        return r.json()


async def tool_schedule_by_slot(slot_id: str, cnp: str | None = None):
    async with make_async_client() as client:
        payload = {"slot_id": slot_id}
        if cnp:
            payload["cnp"] = cnp
        r = await client.post(f"{HUB_URL}/appointments", json=payload)
        r.raise_for_status()
        return r.json()


async def tool_reschedule(appt_id: str, new_slot_id: str) -> dict:
    """
    Reschedule an existing CEI appointment to a new slot.
    """
    async with make_async_client() as client:
        r = await client.patch(f"{HUB_URL}/appointments/{appt_id}", json={"slot_id": new_slot_id})
        r.raise_for_status()
        return r.json()


async def tool_cancel_appointment(appt_id: str) -> dict:
    """
    Cancel an existing CEI appointment.
    """
    async with make_async_client() as client:
        r = await client.delete(f"{HUB_URL}/appointments/{appt_id}")
        r.raise_for_status()
        return r.json()


# --------------------------- FILE UPLOAD + OCR ---------------------------

async def tool_upload(file_bytes: bytes, filename: str, docHint: str = "auto", sid: str = "anon") -> dict:
    """
    Forward a file to the Primarie Locala mock OCR endpoint.
    IMPORTANT: include `sid` so uploads are tied to the chat/form session.
    """
    files = {"file": (filename, file_bytes, "application/octet-stream")}
    data = {"docHint": docHint, "sid": sid}
    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/uploads", files=files, data=data)
        r.raise_for_status()
        return r.json()



# --------------------------- NOTIFICATIONS ---------------------------

async def tool_notify_email(to: str, subject: str, body: str) -> dict:
    """
    Send an email notification via the mock webhook.
    """
    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/notify/email", json={"to":to,"subject":subject,"body":body})
        r.raise_for_status()
        return r.json()


async def tool_notify_sms(to: str, body: str) -> dict:
    """
    Send an SMS notification via the mock webhook.
    """
    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/notify/sms", json={"to":to,"body":body})
        r.raise_for_status()
        return r.json()


