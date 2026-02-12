# authz.py
# Role-based access control (RBAC) helpers.
#
# Design goals:
#  - Keep checks centralized (one place to review policy)
#  - Support both route-level protection (FastAPI dependencies)
#  - Support agent/action-level checks via (role, scopes) passed in state

from __future__ import annotations

from typing import Iterable, Optional, Dict, Set, List
from fastapi import Depends, HTTPException, Request

from auth import get_user_from_cookie, UserCtx

ROLE_PERMS: Dict[str, Set[str]] = {
    "citizen": {"uploads:list"},
    "operator": {
        "case:read",
        "case:update",
        "schedule:write",
        "uploads:list",
    },
    "supervisor": {
        "case:read",
        "case:update",
        "case:assign",
        "case:close",
        "schedule:write",
        "uploads:list",
        "uploads:purge",
        "audit:read",
    },
}

def _normalize_scopes(scopes: Optional[Iterable[str]]) -> Set[str]:
    if not scopes:
        return set()
    return {str(s).strip() for s in scopes if str(s).strip()}

def has_perm(role: str, scopes: Iterable[str], perm: str) -> bool:
    perm = (perm or "").strip()
    if not perm:
        return False

    scope_set = _normalize_scopes(scopes)
    if perm in scope_set:
        return True

    role_set = ROLE_PERMS.get((role or "").strip().lower(), set())
    return perm in role_set

def require_login(request: Request) -> UserCtx:
    u = get_user_from_cookie(request)
    if not u:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return UserCtx(**u)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid auth context")

def require_role(allowed: List[str]):
    allowed_norm = {a.strip().lower() for a in (allowed or []) if a and a.strip()}

    def _dep(user: UserCtx = Depends(require_login)) -> UserCtx:
        if user.role.strip().lower() not in allowed_norm:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return _dep

def require_perm(perm: str):
    def _dep(user: UserCtx = Depends(require_login)) -> UserCtx:
        if not has_perm(user.role, user.scopes, perm):
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return _dep

def actor_from_userctx(user: Optional[UserCtx]) -> dict:
    if not user:
        return {"sub": "anonymous", "role": "citizen", "scopes": []}
    return {"sub": user.email, "role": user.role, "scopes": list(user.scopes or [])}
