from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlmodel import Session
from observability import current_trace_ids
from db import AuditLog, engine


SENSITIVE_KEYS = {
    "cnp",
    "email",
    "telefon",
    "phone",
    "adresa",
    "address",
    "nume",
    "prenume",
    "name",
}


def _hash_value(v: str) -> str:
    h = hashlib.sha256(v.encode("utf-8", errors="ignore")).hexdigest()
    return h[:12]


def redact_details(details: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return a policy-safe copy of details (no raw PII).

    - Removes high-risk fields and replaces with short hashes.
    - Keeps structural info useful for debugging.
    """
    d = dict(details or {})
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if k in SENSITIVE_KEYS:
            if v is None:
                continue
            out[k + "_hash"] = _hash_value(str(v))
            continue
        # Keep small primitives; drop huge payloads
        if isinstance(v, (str, int, float, bool)) or v is None:
            s = str(v)
            out[k] = s[:500] if isinstance(v, str) else v
        else:
            # Avoid dumping nested structures; keep a hash marker
            try:
                out[k + "_hash"] = _hash_value(json.dumps(v, ensure_ascii=False)[:2000])
            except Exception:
                out[k] = "<redacted>"
    return out


def write_audit(
    actor: str,
    action: str,
    entity_type: str = "",
    entity_id: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort audit write (never raise)."""
    try:
        safe = redact_details(details)

        # Put audit trace IDs in the log for easier correlation when debugging
        ids = current_trace_ids()
        if ids:
            safe = dict(safe)
            safe.update(ids)

        with Session(engine) as s:
            s.add(
                AuditLog(
                    actor=actor or "system",
                    action=action or "UNKNOWN",
                    entity_type=entity_type or "",
                    entity_id=entity_id or "",
                    details_json=json.dumps(safe, ensure_ascii=False),
                )
            )
            s.commit()
    except Exception:
        return
