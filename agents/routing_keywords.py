from __future__ import annotations

import re
from typing import Optional


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


def keyword_intent(text: str) -> str:
    """Deterministic (non-LLM) intent detection for Romanian phrasing.

    Notes:
    - Uses regex with word boundaries for short tokens (ex: CI).
    - Keep conservative: return 'unknown' if ambiguous.
    """
    t = (text or "").strip().lower()
    if not t:
        return "unknown"

    # Operator / backoffice
    if _has_any(t, [r"\boperator\b", r"\btasks?\b", r"\bcaz(uri)?\b", r"\bdosar\b", r"\badmin\b"]):
        return "operator"

    # Social aid / benefits
    if _has_any(t, [
        r"ajutor\s+social",
        r"\bvmi\b",
        r"venit\s+minim",
        r"benefici(i|u)",
        r"\bassistenta\s+sociala\b",
    ]):
        return "social"

    # Identity card
    if _has_any(t, [
        r"carte\s+de\s+identitate",
        r"\bbuletin\b",
        r"\bci\b",
        r"\bc\.i\.\b",
        r"preschimbare\b",
        r"expir(a|at)",
        r"schimbare\s+domiciliu",
        r"viza\s+de\s+flotant",
    ]):
        return "carte_identitate"

    # Taxes / local payments (example 3rd use case scaffold)
    if _has_any(t, [
        r"\btaxe\b",
        r"impozit",
        r"ghiseul",
        r"plata\b",
        r"\bamenzi\b",
    ]):
        return "taxe"

    # Legal / procedure questions
    if _has_any(t, [r"lege", r"hotarare", r"regulament", r"care\s+este\s+procedura", r"acte\s+necesare"]):
        return "legal"

    return "unknown"


def looks_like_scheduling(text: str) -> bool:
    t = (text or "").lower()
    return _has_any(t, [
        r"programar(e|i)",
        r"\bslot(uri)?\b",
        r"rezerv(a|are)",
        r"reprogram",
        r"cand\s+e\s+liber",
        r"appointment",
        r"schedule",
    ])
