# main.py
# Entry point FastAPI application that exposes:
#  - Public Chat UI (/)
#  - Operator dashboard (/operator) protected by a simple cookie-based JWT
#  - Login/logout flows
#  - Upload endpoint with file validation + thumbnail creation
#  - Thin "proxy" helpers for listing slots, rescheduling and canceling appointments
#  - Mounts the orchestrator API under /api
#
# NOTE: This app expects the two mock services (CEI-HUB and Primarie Locala)
# to be available at HUB_URL and LOCAL_URL. If you prefer to run everything
# from a single uvicorn process, you can mount those FastAPI apps as sub-apps

from dotenv import load_dotenv
load_dotenv()  # Load .env before any other imports that need env vars

import os, io, json, mimetypes, uuid, time
from typing import Optional
from agents.http_client import make_async_client
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from db import getRandomSessionId
from services.auth import require_role

# Running mode: "mounted" (default) runs the mock services as separate processes,
# "split" mounts them as sub-apps (easier for local testing, but not realistic).
# You can set the RUN_MODE env var to override.
RUN_MODE = os.getenv("RUN_MODE", "mounted").lower()  # "mounted" | "split"

# Import the orchestrator API router (chat + MCP-tool endpoints)
from agents.orchestrator import router as orch_router

# OpenTelemetry initialization (optional, configured via env vars)
from observability import init_otel

# Authentication helpers for the operator UI (JWT in a cookie)
from services.auth import authenticate, create_token, get_user_from_cookie

# Policy-safe audit log (DB: AuditLog)
from audit import write_audit
from fastapi import Depends
# DB initialization (creates tables on startup)
from db import init_db, engine, Upload
from services.auth import require_perm

from sqlmodel import Session, select

APP_TITLE = "MCP CEI/CIS/CIP Demo"

# External service URLs (mock services)
# Compute defaults based on RUN_MODE (can still be overridden by explicit HUB_URL/LOCAL_URL)
_default_hub = "http://localhost:8000/hub" if RUN_MODE == "mounted" else "http://localhost:8001"
_default_local = "http://localhost:8000/local" if RUN_MODE == "mounted" else "http://localhost:8002"

HUB_URL = os.getenv("HUB_URL", _default_hub)
LOCAL_URL = os.getenv("LOCAL_URL", _default_local)

# Create main FastAPI app and include orchestrator API at /api/*
app = FastAPI(title=APP_TITLE)

init_otel(service_name="public-admin-demo")  # enable with OTEL_ENABLE=1

app.include_router(orch_router, prefix="/api")
#app.middleware("http")(log_requests)

# Static files + server-side templates (Jinja2)
os.makedirs("static/uploads/thumbs", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.middleware("http")
async def log_upload_poller(request: Request, call_next):
    t0 = time.time()
    if request.url.path.startswith("/local/uploads"):
        ua = request.headers.get("user-agent", "-")
        ref = request.headers.get("referer", "-")
        origin = request.headers.get("origin", "-")
        caller = request.headers.get("X-Caller", "-")
        print(f"[UPLOADS] {request.method} {request.url} UA={ua} REF={ref} ORIGIN={origin} CALLER={caller}")
    resp = await call_next(request)

    # Policy-safe audit trail: low-cardinality request log.
    # Avoid logging raw PII or full bodies.
    try:
        user = get_user_from_cookie(request)
        actor = (user.get("username") if isinstance(user, dict) else None) or "anonymous"
    except Exception:
        actor = "anonymous"

    try:
        sid = request.query_params.get("sid") or request.query_params.get("session_id")
        # For multipart forms, sid is not available here without reading the body.
        details = {
            "method": request.method,
            "path": request.url.path,
            "status": getattr(resp, "status_code", None),
            "duration_ms": int((time.time() - t0) * 1000),
            "sid": sid,
        }
        write_audit(actor=actor, action="HTTP", entity_type="http", entity_id=request.url.path, details=details)
    except Exception:
        pass

    return resp

@app.on_event("startup")
def _startup():
    """
    Initialize persistent SQLite database on app startup.
    """
    init_db()

    # --- mount mock services only when RUN_MODE == "mounted"
    if RUN_MODE == "mounted":
        # Importing here avoids side effects when running split mode
        from services.cei_hub_mock import app as hub_app
        from services.primarie_local_mock import local as local_app
        app.mount("/hub", hub_app)
        app.mount("/local", local_app)

    print(f"[BOOT] RUN_MODE={RUN_MODE}  HUB_URL={HUB_URL}  LOCAL_URL={LOCAL_URL}")

@app.get("/local-health")
def local_health_hint():
    return {
        "ok": True,
        "hint": "Try /local/docs, /local/cases, /local/tasks, /local/uploads, /local/slots-social"
    }

# ---------------------------- User ---------------------------

# CI case
@app.get("/user-carte_identitate", response_class=HTMLResponse)
async def user_ci_page(request: Request, sid: Optional[str] = None):
    if not sid:
        sid = f"ci-{getRandomSessionId()}"

    return templates.TemplateResponse(
        "user_ci.html",
        {"request": request, "app_title": APP_TITLE, "sid": sid, "ui_context": "carte_identitate"}
    )
# Social case
@app.get("/user-social", response_class=HTMLResponse)
async def user_social_page(request: Request, sid: Optional[str] = None):
    if not sid or "entry" in sid:
        sid = f"social-{getRandomSessionId()}"

    return templates.TemplateResponse(
        "user_social.html",
        {"request": request, "app_title": APP_TITLE, "sid": sid, "ui_context": "social"}
    )


# Taxe case (scaffold demo)
@app.get("/user-taxe", response_class=HTMLResponse)
async def user_taxe_page(request: Request, sid: Optional[str] = None):
    if not sid:
        sid = f"taxe-{getRandomSessionId()}"

    return templates.TemplateResponse(
        "user_taxe.html",
        {"request": request, "app_title": APP_TITLE, "sid": sid, "ui_context": "taxe"}
    )

# --------------------------- AUTH PAGES ---------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """
    Render the operator login page. Uses a cookie to store the access_token.
    """
    return templates.TemplateResponse("login.html", {"request": request, "app_title": APP_TITLE, "err": None})


@app.post("/login")
async def login(request: Request):
    """
    Handle login. Accepts either the HTML form (email/password) or a JSON body
    ({"username"|"email", "password"}) for programmatic/API clients.
    On success sets the JWT cookie; form clients are redirected to /operator,
    JSON clients get 200 with a small JSON body.
    """
    wants_json = (request.headers.get("content-type") or "").startswith("application/json")
    if wants_json:
        data = await request.json()
        email = (data.get("email") or data.get("username") or "").strip()
        password = data.get("password") or ""
    else:
        data = await request.form()
        email = (data.get("email") or "").strip()
        password = data.get("password") or ""

    user = authenticate(email, password)
    if not user:
        if wants_json:
            return JSONResponse({"ok": False, "error": "invalid_credentials"}, status_code=401)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "app_title": APP_TITLE, "err": "Invalid credentials"},
            status_code=401
        )

    token = create_token(email)
    if wants_json:
        resp = JSONResponse({"ok": True, "email": user["email"], "role": user["role"]})
    else:
        resp = RedirectResponse("/operator", status_code=303)
    # Store token in a cookie; httponly prevents JavaScript from reading it
    resp.set_cookie("access_token", token, httponly=True, samesite="lax")
    return resp


def _clear_auth_cookie(resp):
    """Emit an explicit expired cookie (delete_cookie renders an empty quoted value)."""
    resp.headers.append(
        "set-cookie",
        "access_token=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; "
        "HttpOnly; SameSite=lax",
    )
    return resp


@app.api_route("/logout", methods=["GET", "POST"])
def logout(request: Request):
    """
    Clear the auth cookie. GET redirects to the chat homepage (browser flow);
    POST returns JSON (API flow).
    """
    if request.method == "POST":
        return _clear_auth_cookie(JSONResponse({"ok": True}))
    return _clear_auth_cookie(RedirectResponse("/", status_code=303))


# --------------------------- PUBLIC CHAT UI ---------------------------

@app.get("/", response_class=HTMLResponse)
async def chat_ui(request: Request):
    """
    Render the Chat UI. The page calls /api/chat via fetch() to run the flow.
    """
    return templates.TemplateResponse("chat.html", {"request": request, "app_title": APP_TITLE})


# --------------------------- OPERATOR DASHBOARD (PROTECTED) ---------------------------

@app.get("/operator", response_class=HTMLResponse)
async def operator_ui(request: Request):
    """
    Render the operator dashboard.
    Requires a valid JWT in the 'access_token' cookie.
    Displays:
      - Cases list from the Primarie Locala
      - Available slots from the CEI-HUB (for rescheduling)
      - HITL task queue list
    """
    user = get_user_from_cookie(request)
    if not user or (user.get("role") or "").lower() not in {"operator", "supervisor"}:
        return RedirectResponse("/login", status_code=303)

    async with make_async_client() as client:
        cases = (await client.get(f"{LOCAL_URL}/cases")).json()
        slots = (await client.get(f"{HUB_URL}/slots", params={"location_id":"Bucuresti-S1"})).json()
        tasks = (await client.get(f"{LOCAL_URL}/tasks")).json()

    return templates.TemplateResponse(
        "operator.html",
        {"request": request,
         "cases": cases,
         "slots": slots,
         "tasks": tasks,
         "user": user,
         "sid": f"op-{user['email'].split('@')[0]}"  # chat session for operator
         }
    )


@app.post("/operator/advance")
async def operator_advance(
    request: Request,
    user=Depends(require_role(["operator", "supervisor"])),
    case_id: str = Form(...),
    next_status: str = Form(...),
):
    """
    Update case status via Primarie Locala mock service.
    """

    async with make_async_client() as client:
        await client.patch(f"{LOCAL_URL}/cases/{case_id}", params={"status": next_status})

    return RedirectResponse(url="/operator", status_code=303)

@app.get("/operator/slots")
async def op_slots(request: Request, user=Depends(require_role(["operator","supervisor"]))):
    """
    Helper endpoint for UI: fetch available CEI-HUB slots for a fixed location.
    """

    async with make_async_client() as client:
        r = await client.get(f"{HUB_URL}/slots", params={"location_id":"Bucuresti-S1"})
        return r.json()


@app.post("/operator/reschedule")
async def op_reschedule(
    request: Request,
    user=Depends(require_role(["operator", "supervisor"])),
    case_id: str = Form(...),
    appt_id: str = Form(...),
    slot_id: str = Form(...),
):
    """
    Reschedule a CEI appointment.
    Calls orchestrator's /api/reschedule endpoint (consolidating business logic there),
    then ensures the case is marked as SCHEDULED.
    """

    async with make_async_client() as client:
        base = str(request.base_url).rstrip("/")
        r = await client.post(f"{base}/api/reschedule", json={"appt_id": appt_id, "new_slot_id": slot_id})
        r.raise_for_status()
        await client.patch(f"{LOCAL_URL}/cases/{case_id}", params={"status":"SCHEDULED"})

    return RedirectResponse(url="/operator", status_code=303)


@app.post("/operator/cancel")
async def op_cancel(
    request: Request,
    user=Depends(require_role(["operator", "supervisor"])),
    case_id: str = Form(...),
    appt_id: str = Form(...),
):
    """
    Cancel a CEI appointment via orchestrator /api/cancel endpoint.
    """

    async with make_async_client() as client:
        base = str(request.base_url).rstrip("/")
        r = await client.post(f"{base}/api/cancel", json={"appt_id": appt_id})
        r.raise_for_status()

    return RedirectResponse(url="/operator", status_code=303)


# --------------------------- HITL QUEUE ACTIONS ---------------------------

# The queue is exposed twice: as an HTML form flow for the dashboard, and as a
# JSON API for programmatic clients and the test suite. Both share one role gate.

# Backend statuses -> stable API vocabulary.
_TASK_STATUS_API = {"OPEN": "open", "ASSIGNED": "claimed", "DONE": "completed"}


def _task_json(t: dict) -> dict:
    raw = (t or {}).get("status") or ""
    return {
        "task_id": (t or {}).get("id"),
        "case_id": (t or {}).get("case_id"),
        "kind": (t or {}).get("kind"),
        "status": _TASK_STATUS_API.get(raw.upper(), raw.lower()),
        "assignee": (t or {}).get("assignee"),
        "notes": (t or {}).get("notes"),
    }


async def _read_task_id(request: Request) -> tuple[Optional[int], bool, dict]:
    """Return (task_id, wants_json, body) accepting either a JSON or form body."""
    wants_json = (request.headers.get("content-type") or "").startswith("application/json")
    if wants_json:
        body = await request.json()
    else:
        body = dict(await request.form())
    try:
        return int(body.get("task_id")), wants_json, body
    except (TypeError, ValueError):
        return None, wants_json, body


@app.get("/operator/tasks")
async def operator_tasks_list(
    status: Optional[str] = None,
    user=Depends(require_role(["operator", "supervisor"])),
):
    """List HITL tasks as JSON. Anonymous callers get 401, other roles 403."""
    async with make_async_client() as client:
        r = await client.get(f"{LOCAL_URL}/tasks", params={"status": status} if status else None)
        tasks = r.json()
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])
    return JSONResponse([_task_json(t) for t in (tasks or [])])


@app.post("/operator/tasks/enqueue")
async def operator_task_enqueue(
    request: Request,
    user=Depends(require_role(["operator", "supervisor"])),
):
    """Create a HITL task for a case."""
    body = await request.json()
    payload = {
        "case_id": body.get("case_id") or "",
        "kind": body.get("kind") or "MANUAL_VERIFY",
        "notes": json.dumps(body.get("payload") or {}, ensure_ascii=False),
    }
    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/tasks", json=payload)
        r.raise_for_status()
        created = r.json()
    task = created.get("task", created)
    return _task_json(task)


@app.post("/operator/tasks/claim")
async def claim_task(
    request: Request,
    user=Depends(require_role(["operator", "supervisor"])),
):
    """
    Claim a HITL task (assign to current operator).
    Accepts a JSON body (returns JSON) or the dashboard form (redirects).
    """
    task_id, wants_json, _ = await _read_task_id(request)
    if task_id is None:
        raise HTTPException(status_code=422, detail="task_id is required")

    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/tasks/{task_id}/claim",
                              json={"assignee": user.email})
        r.raise_for_status()
        result = r.json()

    if wants_json:
        return _task_json({**(result.get("task") or {}), "case_id": None})
    return RedirectResponse("/operator", status_code=303)


@app.post("/operator/tasks/complete")
async def complete_task_api(
    request: Request,
    user=Depends(require_role(["operator", "supervisor"])),
):
    """Complete a HITL task (JSON API counterpart of /operator/tasks/done)."""
    task_id, wants_json, body = await _read_task_id(request)
    if task_id is None:
        raise HTTPException(status_code=422, detail="task_id is required")

    notes = body.get("notes")
    if notes is None and body.get("result") is not None:
        notes = json.dumps(body.get("result"), ensure_ascii=False)

    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/tasks/{task_id}/complete",
                              json={"notes": notes or ""})
        r.raise_for_status()
        result = r.json()

    if wants_json:
        return _task_json({**(result.get("task") or {}), "case_id": None})
    return RedirectResponse("/operator", status_code=303)


@app.post("/operator/tasks/done")
async def done_task(
    request: Request,
    user=Depends(require_role(["operator", "supervisor"])),
    task_id: int = Form(...),
    notes: str = Form(""),
):
    """
    Mark a HITL task as DONE with optional notes.
    """

    async with make_async_client() as client:
        await client.post(f"{LOCAL_URL}/tasks/{task_id}/complete", json={"notes": notes})

    return RedirectResponse("/operator", status_code=303)


# --------------------------- UPLOAD + THUMBNAILS + OCR FORWARDING ---------------------------

# File constraints (can override via env)
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "10"))
ALLOWED_MIME = {"image/jpeg","image/png","application/pdf"}

@app.post("/upload")
async def upload_doc(
    request: Request,
    file: UploadFile = File(...),
    docHint: str = Form(default="auto"),
    sid: str = Form(default="anon")  # NEW: session link
):
    """
    Upload a user document (PDF/JPG/PNG), validate size/type,
    generate a thumbnail for images, forward to OCR mock,
    and persist metadata (session-aware).
    """
    mime = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, f"Unsupported type: {mime}. Allowed: {', '.join(sorted(ALLOWED_MIME))}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"File too large (> {MAX_UPLOAD_MB} MB).")

    # Save under /static/uploads
    fn = f"{uuid.uuid4().hex}_{file.filename}"
    path = os.path.join("static", "uploads", fn)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)

    # Optional thumbnail
    thumb_path = None
    if mime in {"image/jpeg", "image/png"}:
        try:
            im = Image.open(io.BytesIO(content))
            im.thumbnail((320, 320))
            thumb_path = os.path.join("static", "uploads", "thumbs", f"th_{fn}.jpg")
            im.convert("RGB").save(thumb_path, "JPEG", quality=80)
        except Exception:
            thumb_path = None

    # Forward to Primarie Locala OCR mock
    files = {"file": (file.filename, content, mime)}
    data = {"docHint": docHint, "sid": sid}
    async with make_async_client() as client:
        r = await client.post(f"{LOCAL_URL}/uploads", files=files, data=data)
        r.raise_for_status()
        ocr = r.json() if r.content else {}

    # --- Persist metadata in DB ---
    upload_kind = None
    upload_text = None
    if isinstance(ocr, dict):
        up = ocr.get("upload") or {}
        if isinstance(up, dict):
            upload_kind = up.get("kind")
            upload_text = up.get("ocr_text")

    if not upload_kind:
        upload_kind = docHint if docHint != "auto" else None


    # Write metadata in DB with a "latest wins" policy per session+kind: if the same kind is uploaded again, remove previous record and files so UI shows only the latest upload for that kind.
    with Session(engine) as s:
        if sid and upload_kind:
            old_rows = s.exec(select(Upload).where(Upload.session_id == sid, Upload.kind == upload_kind)).all()
            for old in old_rows:
                try:
                    # Best-effort delete stored files
                    if old.path:
                        p = old.path.lstrip("/")
                        if os.path.exists(p):
                            os.remove(p)
                    if old.thumb:
                        tp = old.thumb.lstrip("/")
                        if os.path.exists(tp):
                            os.remove(tp)
                except Exception:
                    pass
                s.delete(old)
            s.commit()

        rec = Upload(
            session_id=sid,
            filename=file.filename,
            path="/" + path,
            thumb=("/" + thumb_path) if thumb_path else None,
            kind=upload_kind,
            ocr_text=upload_text,
        )
        s.add(rec)
        s.commit()

        # Policy-safe audit: do not store raw OCR or file bytes.
        try:
            user = get_user_from_cookie(request)
            actor = (user.get("username") if isinstance(user, dict) else None) or "anonymous"
            write_audit(
                actor=actor,
                action="UPLOAD",
                entity_type="upload",
                entity_id=str(rec.id or ""),
                details={
                    "sid": sid,
                    "filename": file.filename,
                    "mime": mime,
                    "kind": upload_kind,
                    "size": len(content),
                },
            )
        except Exception:
            pass

    return JSONResponse(
        {
            "saved": True,
            "sid": sid,
            "path": "/" + path,
            "thumb": ("/" + thumb_path) if thumb_path else None,
            "ocr": ocr,
            "recognized": ocr.get("recognized") if isinstance(ocr, dict) else [],
        }
    )


@app.get("/uploads")
def uploads_list(session_id: str):
    """Public API: list uploads for a session."""
    with Session(engine) as s:
        rows = s.exec(select(Upload).where(Upload.session_id == session_id).order_by(Upload.id)).all()

    items = [r.dict() for r in rows]
    recognized = []
    seen = set()
    for it in items:
        k = (it.get("kind") or "").strip().lower()
        if k and k not in seen:
            seen.add(k)
            recognized.append(k)

    return {"session_id": session_id, "recognized": recognized, "items": items}


@app.delete("/uploads/purge")
async def uploads_purge(session_id: str, _user=Depends(require_perm("uploads:purge"))):
    """Public API: purge uploads for a session (DB + local mock best-effort)."""
    # Best-effort purge on the local mock
    try:
        async with make_async_client() as client:
            await client.delete(f"{LOCAL_URL}/uploads/purge", params={"session_id": session_id})
    except Exception:
        pass

    with Session(engine) as s:
        rows = s.exec(select(Upload).where(Upload.session_id == session_id)).all()
        for r in rows:
            s.delete(r)
        s.commit()
    return {"ok": True, "session_id": session_id}


@app.get("/api/uploads")
def uploads_list_legacy(sid: str):
    # Backwards compatible alias
    return uploads_list(session_id=sid)

@app.get("/confirm-carte_identitate", response_class=HTMLResponse)
def confirm_ci(request: Request, sid: str, decided: str = "auto"):
    # decided is passed from user_ci redirect; we still show chat so users can schedule CEI if needed
    return templates.TemplateResponse("confirm_ci.html", {
        "request": request,
        "sid": sid,
        "decided": decided,
    })


@app.api_route("/healthz", methods=["GET"])
@app.api_route("/health", methods=["GET"])
def health():
    """
    Simple health-check endpoint for probes. Exposed at both /healthz and /health.
    """
    return {"ok": True, "status": "ok", "agent_mode": os.getenv("AGENT_MODE", "v2")}
