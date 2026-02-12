# auth.py
# Minimal authentication layer for the operator dashboard.
# Uses:
#   - Password hashing (passlib[bcrypt])
#   - OAuth2PasswordBearer (unused here in UI flow, but available)
#   - Signed JWT tokens (python-jose) stored in an HttpOnly cookie
#
# For simplicity, users are kept in-memory (USERS dict). You can migrate this
# to a persistent DB table later.

import os, time
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel

# Secret + algorithm for JWT signing
SECRET_KEY = os.getenv("AUTH_SECRET", "demo_super_secret")
ALGO = "HS256"
ACCESS_TOKEN_EXPIRE = 60 * 60 * 8  # 8 hours

# Simple password context (Bcrypt)
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Demo user store (replace with a DB if needed)
# An operator and a supervisor user are pre-seeded, both with password "demo1234".
USERS = {
    "operator@example.com": {
        "email": "operator@example.com",
        "name": "Operator Demo",
        "hashed": pwd.hash("demo1234"),
        "role": "operator",
        "scopes": ["case:read", "case:update", "schedule:write", "uploads:list"],
    },
    "supervisor@example.com": {
        "email": "supervisor@example.com",
        "name": "Supervisor Demo",
        "hashed": pwd.hash("demo1234"),
        "role": "supervisor",
        "scopes": [
            "case:read",
            "case:update",
            "case:assign",
            "case:close",
            "schedule:write",
            "uploads:list",
            "uploads:purge",
            "audit:read",
        ],
    },
}

class UserCtx(BaseModel):
    email: str
    name: Optional[str] = None
    role: str = "operator"
    scopes: list[str] = []


# OAuth2 bearer scheme (not strictly necessary with cookie-based UI,
# but useful if you later build a programmatic API)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

class Token(BaseModel):
    """
    Response model for a token endpoint (not used in the UI flow).
    """
    access_token: str
    token_type: str


def authenticate(email: str, password: str):
    """
    Validate credentials against USERS dictionary.
    Returns user dict on success, None otherwise.
    """
    u = USERS.get(email)
    if not u or not pwd.verify(password, u["hashed"]):
        return None
    return {"email": u["email"], "name": u["name"], "role": u["role"]}


def create_token(sub: str) -> str:
    """
    Create a signed JWT for the provided subject.
    The token encodes issued-at and expiry times.
    """
    now = int(time.time())
    # Check the database for the user to include role/scopes in the token
    # (optional, but useful if you want to enforce scopes in API routes later)
    u = USERS.get(sub) or {}
    payload = {
        "sub": sub,
        "role": u.get("role", "operator"),
        "scopes": u.get("scopes", []),
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRE,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGO)


def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Standard FastAPI dependency to extract a user from Authorization: Bearer <token>.
    Not used by the cookie-based UI, but ready for API routes if needed.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGO])
        sub = payload.get("sub")
        if not sub or sub not in USERS:
            raise HTTPException(status_code=401, detail="Invalid user")
        return USERS[sub]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_user_from_cookie(request: Request) -> Optional[dict]:
    """
    Helper used by templates/UI endpoints.
    Reads the 'access_token' cookie and returns the user dict if valid; otherwise None.
    """
    tok = request.cookies.get("access_token")
    if not tok:
        return None
    try:
        payload = jwt.decode(tok, SECRET_KEY, algorithms=[ALGO])
        sub = payload.get("sub")
        u = USERS.get(sub)

        res = {
            "email": u.get("email") or payload.get("email"),
            "name": u.get("name") or payload.get("name"),
            "role": u.get("role") or payload.get("role", "operator"),
            "scopes": u.get("scopes") or payload.get("scopes", []),
        }

    except Exception:
        return None
