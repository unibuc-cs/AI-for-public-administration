# agents/settings.py
from __future__ import annotations
import os

def env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1","true","yes","y","on"}

LLM_USE: bool = env_flag("LLM_USE", False)
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-5-mini")
