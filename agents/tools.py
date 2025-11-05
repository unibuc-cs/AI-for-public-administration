# agents/tools.py
# A lightweight set of "MCP-like" tools the orchestrator can call.
# Each tool encapsulates a clear external side-effect or query:
#   - Eligibility mapping (auto decide CEI/CIS/CIP)
#   - Document requirement / missing detection
#   - Case submission to Primărie Locală
#   - Payment & Signature
#   - Scheduling via CEI-HUB (and local fallback)
#   - Reschedule/Cancel appointments
#   - File upload to OCR mock
#   - Notifications (email/SMS) via webhooks
#
# The orchestrator coordinates these tools in a consistent flow.

import os, json
import httpx

# External service endpoints (mock servers)
HUB_URL = os.getenv("HUB_URL", "http://localhost:8001")
LOCAL_URL = os.getenv("LOCAL_URL", "http://localhost:8002")


# --------------------------- ELIGIBILITY & DOCS ---------------------------

def tool_eligibility(eligibility_reason: str) -> dict:
    """
    Map an eligibility reason to a recommended application type.
    This mirrors a simplistic rule-based system.
    """
    mapping = {"AGE_14":"CEI", "EXP_60":"CEI", "CHANGE":"CEI", "LOSS":"CIP"}
    decided = mapping.get(eligibility_reason, "CIS")
    return {"decided_type": decided, "reason": eligibility_reason}


def tool_docs_required(app_type: str) -> dict:
    """
    Return the list of required documents for a given application type.
    """
    base = ["cert_nastere", "dovada_adresa"]
    if app_type in ("CIS","CEI"):
        base.append("ci_veche")
    return {"required": base}


def tool_docs_missing(app_type: str, docs: list[dict]) -> dict:
    """
    Compare required documents vs. those provided and return the missing ones.
    """
    required = set(tool_docs_required(app_type)["required"])
    provided = {d["kind"] for d in docs if d.get("status") == "ok"}
    return {"missing": list(required - provided)}


# --------------------------- CASE SUBMISSION ---------------------------

async def tool_case_submit(person: dict, app: dict) -> dict:
    """
    Create a new case via the Primărie Locală mock service.
    Expects {"person": {...}, "application": {...}} so primarie_local_mock can infer program/type.
    For CI: app should contain "type": "CEI"/"CIS"/"CIP" and optionally "docs".
    For AS: app should contain "program": "AS" and "docs".
    """
    payload = {
        "person": person or {},
        "application": app or {}
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{LOCAL_URL}/cases", json=payload)
        r.raise_for_status()
        return r.json()


# --------------------------- PAYMENT & SIGNATURE ---------------------------

async def tool_payment(case_id: str, amount: float) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{LOCAL_URL}/payments", json={"case_id": case_id, "amount": amount})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"skipped": True, "reason": f"payments endpoint missing: {e}"}

async def tool_signature(case_id: str) -> dict:
    try:
        async with httpx.AsyncClient() as client:
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
    async with httpx.AsyncClient() as client:
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
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{LOCAL_URL}/reserve-social", json={"slot_id": slot_id, "cnp": cnp})
        r.raise_for_status()
        return r.json()


async def tool_schedule_by_slot(slot_id: str, cnp: str | None = None):
    async with httpx.AsyncClient() as client:
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
    async with httpx.AsyncClient() as client:
        r = await client.patch(f"{HUB_URL}/appointments/{appt_id}", json={"slot_id": new_slot_id})
        r.raise_for_status()
        return r.json()


async def tool_cancel_appointment(appt_id: str) -> dict:
    """
    Cancel an existing CEI appointment.
    """
    async with httpx.AsyncClient() as client:
        r = await client.delete(f"{HUB_URL}/appointments/{appt_id}")
        r.raise_for_status()
        return r.json()


# --------------------------- FILE UPLOAD + OCR ---------------------------

async def tool_upload(file_bytes: bytes, filename: str, kind_hint: str = "auto", sid: str = "anon") -> dict:
    """
    Forward a file to the Primărie Locală mock OCR endpoint.
    IMPORTANT: include `sid` so uploads are tied to the chat/form session.
    """
    files = {"file": (filename, file_bytes, "application/octet-stream")}
    data = {"kind_hint": kind_hint, "sid": sid}
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{LOCAL_URL}/uploads", files=files, data=data)
        r.raise_for_status()
        return r.json()



# --------------------------- NOTIFICATIONS ---------------------------

async def tool_notify_email(to: str, subject: str, body: str) -> dict:
    """
    Send an email notification via the mock webhook.
    """
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{LOCAL_URL}/notify/email", json={"to":to,"subject":subject,"body":body})
        r.raise_for_status()
        return r.json()


async def tool_notify_sms(to: str, body: str) -> dict:
    """
    Send an SMS notification via the mock webhook.
    """
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{LOCAL_URL}/notify/sms", json={"to":to,"body":body})
        r.raise_for_status()
        return r.json()


