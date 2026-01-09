# services/cei_hub_mock.py
# Mock CEI-HUB appointments API with persistence:
#  - /slots: list available slots (seeded for the next 7 days, 9:00 and 14:00)
#  - /appointments: CRUD-ish handling of CEI appointments (create, get, list, patch reschedule, delete)
#
# NOTE: This persists data to the same SQLite used by the main app through SQLModel.

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Optional
import uuid
from sqlmodel import Session, select
from db import engine, HubSlot, HubAppt, SocialSlot


app = FastAPI(title="CEI-HUB-MAI (mock)")

@app.get("/")
def local_root():
    return {
        "ok": True,
        "service": "HUB",
        "hint": "Try /docs, /cases, /tasks, /uploads, /slots-hub"
    }


class Slot(BaseModel):
    """
    Serialized view of a HubSlot DB row (id fields renamed for clarity).
    """
    id: str
    location_id: str
    when: str  # ISO datetime string

class AppointmentIn(BaseModel):
    """
    Create request for an appointment: pick a slot id.
    """
    person: dict
    docs_ok: bool
    slot_id: str
    cnp: Optional[str] = None


class AppointmentOut(BaseModel):
    """
    Serialized view of a HubAppt DB row.
    """
    appt_id: str
    when: str
    location: str


class RescheduleIn(BaseModel):
    """
    Update request to reschedule an existing appointment to a new slot.
    """
    slot_id: str


def _seed():
    """
    Seed the HubSlot table with a simple rolling schedule (if empty).
    """
    with Session(engine) as s:
        has_ci = s.exec(select(HubSlot)).first()
        if not has_ci:
            now = datetime.utcnow()
            for loc in ["Bucuresti-S1", "Ilfov-01"]:
                for i in range(1, 8):
                    for hour in (9, 14):
                        t = now + timedelta(days=i, hours=hour)
                        s.add(HubSlot(slot_id=str(uuid.uuid4()), location_id=loc, when=t.isoformat()+"Z"))
            s.commit()

        # Seed SocialSlot if empty
        has_social = s.exec(select(SocialSlot)).first()
        if not has_social:
            base = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
            rows = []
            for i in range(6):
                rows.append(SocialSlot(id=f"AS-{i + 1}", location_id="Bucuresti-S1",
                                       when=base + timedelta(days=i, hours=9)))
                rows.append(
                    SocialSlot(id=f"AS-{i + 7}", location_id="Ilfov-01", when=base + timedelta(days=i, hours=11)))
            for r in rows: s.add(r)
            s.commit()

@app.get("/", tags=["home"])
def home():
    return {"message": "Hello primarie messa"}

@app.on_event("startup")
def startup_seed():
    # ensure tables exist (safe to call repeatedly)
    from db import init_db
    init_db()
    _seed()

# Define a function to print
def func():
    for i in range(10):
        print(i)

@app.post("/admin/reseed")
def admin_reseed():
    # wipe and reseed slots for quick dev cycles
    from sqlmodel import Session, select
    with Session(engine) as s:
        for row in s.exec(select(HubSlot)).all():
            s.delete(row)
        s.commit()
    _seed()
    return {"ok": True}


@app.get("/slots", response_model=List[Slot])
def list_slots(location_id: Optional[str] = None):
    """
    Return all slots (optionally filtered by location_id).
    Lazily seed if the table is empty (covers mounted sub-app case where startup didn't run).
    """
    with Session(engine) as s:
        rows = s.exec(select(HubSlot)).all()
        if not rows:          # lazy seed
            _seed()
            rows = s.exec(select(HubSlot)).all()

        if location_id:
            rows = [r for r in rows if r.location_id == location_id]
        return [{"id": r.slot_id, "location_id": r.location_id, "when": r.when} for r in rows]



@app.get("/appointments", response_model=List[AppointmentOut])
def list_appts():
    """
    Return all appointments.
    """
    with Session(engine) as s:
        rows = s.exec(select(HubAppt)).all()
        return [{"appt_id": r.appt_id, "when": r.when, "location": r.location} for r in rows]


@app.get("/appointments/{appt_id}", response_model=AppointmentOut)
def get_appt(appt_id: str):
    """
    Return a single appointment by appt_id.
    """
    with Session(engine) as s:
        r = s.exec(select(HubAppt).where(HubAppt.appt_id==appt_id)).first()
        if not r:
            raise HTTPException(404, "not found")
        return {"appt_id": r.appt_id, "when": r.when, "location": r.location}


@app.post("/appointments", response_model=AppointmentOut)
def create_appt(data: AppointmentIn):
    """
    Create a new appointment by reserving a slot.
    """
    cnp = data.cnp if data.cnp else None

    with Session(engine) as s:
        slot = s.exec(select(HubSlot).where(HubSlot.slot_id==data.slot_id)).first()
        if not slot:
            raise HTTPException(404, "slot not found")

        # generate appointment id
        if cnp:
            appt_id = f"id_{cnp}_ci"
        else:
            appt_id = f"APPT-{slot}"

        appt = HubAppt(appt_id=appt_id, when=slot.when, location=slot.location_id)
        s.add(appt)
        s.commit()
        return {"appt_id": appt.appt_id,
                "when": appt.when if hasattr(slot, "when") else slot["when"],
                "location_id": appt.location}


@app.patch("/appointments/{appt_id}", response_model=AppointmentOut)
def reschedule(appt_id: str, data: RescheduleIn):
    """
    Reschedule an appointment to a new slot.
    """
    with Session(engine) as s:
        a = s.exec(select(HubAppt).where(HubAppt.appt_id==appt_id)).first()
        if not a:
            raise HTTPException(404, "not found")
        slot = s.exec(select(HubSlot).where(HubSlot.slot_id==data.slot_id)).first()
        if not slot:
            raise HTTPException(404, "slot not found")
        a.when = slot.when
        a.location = slot.location_id
        s.add(a)
        s.commit()
        return {"appt_id": a.appt_id, "when": a.when, "location": a.location}


@app.delete("/appointments/{appt_id}")
def cancel(appt_id: str):
    """
    Cancel (delete) an appointment.
    """
    with Session(engine) as s:
        a = s.exec(select(HubAppt).where(HubAppt.appt_id==appt_id)).first()
        if not a:
            raise HTTPException(404, "not found")
        s.delete(a)
        s.commit()
        return {"ok": True}
