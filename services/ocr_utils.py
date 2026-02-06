# OCR post-processing utilities.
# Goals:
# - Robust extraction of a few key person fields from OCR text.
# - Handle common Romanian ID card (CI) layouts where labels are on one line and values on the next.


from __future__ import annotations

import re
from typing import Dict, List, Optional


_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_PHONE_RE = re.compile(r"\b(0\d{9})\b")


def _norm_lines(raw: str) -> List[str]:
    if not raw:
        return []
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw.splitlines()]
    return [ln for ln in lines if ln]


def _extract_cnp(raw: str) -> Optional[str]:
    """Extract a 13-digit CNP even if OCR inserts separators/spaces."""
    if not raw:
        return None

    # Common best case: exact 13 digits
    m = re.search(r"\b(\d{13})\b", raw)
    if m:
        return m.group(1)

    # Fallback: collect digits and scan for 13-digit sequences
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 13:
        return None
    # pick first plausible 13-digit window
    for i in range(0, len(digits) - 12):
        cand = digits[i : i + 13]
        if len(cand) == 13:
            return cand
    return None


# Labels that typically indicate a NEW section/field (stop address accumulation)
_ADDR_STOP_LABELS = re.compile(
    r"^(seria\b|nr\b\s*\w|cnp\b|sex\b|s\.n\.p\b|data\b|emisa\b|valabil\b|"
    r"nume\b|prenume\b|name\b|last name\b|first name\b|"
    r"cetatenie\b|nationalitate\b|nationality\b|"
    r"loc nastere\b|place of birth\b|"
    r"semnatura\b|signature\b)",
    flags=re.IGNORECASE,
)


# Prefixes that should be treated as CONTINUATION of an address (even if stop labels exist elsewhere)
_ADDR_CONT_PREFIX = re.compile(
    r"^(nr\.?\b|no\.?\b|et\.?\b|ap\.?\b|bl\.?\b|sc\.?\b|"
    r"jud\.?\b|sector\b|loc\.?\b|oras\b|mun\.?\b|sat\b|"
    r"str\.?\b|calea\b|bd\.?\b|bulevard\b)",
    flags=re.IGNORECASE,
)


def _is_addr_continuation(line: str) -> bool:
    l = (line or "").strip()
    if not l:
        return False
    # Allow typical continuation fragments: "nr. 168", "et. 4", "ap. 32", etc.
    if _ADDR_CONT_PREFIX.search(l):
        return True
    # Also allow pure numeric/short fragments that commonly appear on separate lines.
    if re.fullmatch(r"[0-9]{1,6}", l):
        return True
    return False


def _find_value_after_label(lines: List[str], label_pat: re.Pattern) -> Optional[str]:
    """Find value that appears after a label either on the same line or on the next line."""
    for i, ln in enumerate(lines):
        if not label_pat.search(ln):
            continue
        # Try same line: split after label match
        m = label_pat.search(ln)
        if not m:
            continue
        tail = ln[m.end() :].strip(" :-\t")
        if tail:
            return tail
        # Otherwise next non-empty line
        if i + 1 < len(lines):
            return lines[i + 1].strip()
    return None


def _extract_name_from_ci(lines: List[str]) -> Dict[str, str]:
    """CI often has bilingual headers; values typically appear on the next line."""
    out: Dict[str, str] = {}

    # Common CI headers
    last_name_label = re.compile(r"\b(nume|last name)\b", flags=re.IGNORECASE)
    first_name_label = re.compile(r"\b(prenume|first name|given name)\b", flags=re.IGNORECASE)

    # Many CI layouts:
    #   "Nume/Nom/Last name" (header) then next line is the actual surname
    #   "Prenume/Prénom/First name" then next line is the given name
    ln_last = _find_value_after_label(lines, last_name_label)
    if ln_last and not re.search(r"\b(nom|last name)\b", ln_last, flags=re.IGNORECASE):
        out["nume"] = ln_last.strip()

    ln_first = _find_value_after_label(lines, first_name_label)
    if ln_first and not re.search(r"\b(first name|given name)\b", ln_first, flags=re.IGNORECASE):
        out["prenume"] = ln_first.strip()

    # Fallback: explicit patterns like "Nume: X" "Prenume: Y"
    if "nume" not in out:
        m = re.search(r"\bnume\s*[:=]\s*([A-Za-z\- ]{2,})", "\n".join(lines), flags=re.IGNORECASE)
        if m:
            out["nume"] = m.group(1).strip()
    if "prenume" not in out:
        m = re.search(r"\bprenume\s*[:=]\s*([A-Za-z\- ]{2,})", "\n".join(lines), flags=re.IGNORECASE)
        if m:
            out["prenume"] = m.group(1).strip()

    return out


def _extract_address(lines: List[str]) -> Optional[str]:
    if not lines:
        return None

    # Start markers for CI address
    start_pats = [
        re.compile(r"\b(domiciliu|adresa|address)\b", flags=re.IGNORECASE),
    ]

    start_idx = None
    for i, ln in enumerate(lines):
        if any(p.search(ln) for p in start_pats):
            start_idx = i
            break

    # If no explicit marker, fallback to the first line that looks like a street address.
    if start_idx is None:
        for i, ln in enumerate(lines):
            l = ln.lower()
            if (
                l.startswith("str")
                or " str" in l
                or "calea" in l
                or l.startswith("bd")
                or "bulevard" in l
            ):
                start_idx = i
                break
        if start_idx is None:
            return None

    # Collect from start_idx onward, but stop when a new field label starts.
    buf: List[str] = []
    for j in range(start_idx, len(lines)):
        ln = lines[j].strip()
        if j == start_idx:
            # Remove the label part if present
            ln = re.sub(r"^.*\b(domiciliu|adresa|address)\b\s*[:=-]*\s*", "", ln, flags=re.IGNORECASE).strip()
            if ln:
                buf.append(ln)
            continue

        # If this line is clearly a continuation (nr/et/ap/etc), always keep it.
        if _is_addr_continuation(ln):
            buf.append(ln)
            continue

        # Stop when we hit another label-like line
        if _ADDR_STOP_LABELS.search(ln):
            break

        # Otherwise, keep if it looks like address content and not too short.
        if len(ln) >= 3:
            buf.append(ln)

        # Hard cap: address should not consume too many lines in a demo.
        if len(buf) >= 4:
            break

    if not buf:
        return None
    return ", ".join(buf)


def extract_person_fields(raw: str) -> Dict[str, str]:
    """Extract person fields from OCR text.

    Returns keys (when found):
      - cnp
      - nume
      - prenume
      - adresa
      - email
      - telefon
    """
    lines = _norm_lines(raw)
    if not lines:
        return {}

    out: Dict[str, str] = {}

    cnp = _extract_cnp(raw)
    if cnp:
        out["cnp"] = cnp

    m = _EMAIL_RE.search(raw)
    if m:
        out["email"] = m.group(1)

    m = _PHONE_RE.search(raw)
    if m:
        out["telefon"] = m.group(1)

    out.update(_extract_name_from_ci(lines))

    addr = _extract_address(lines)
    if addr:
        out["adresa"] = addr

    # Cleanup
    for k in list(out.keys()):
        v = str(out[k]).strip()
        if not v or v.lower() in ("null", "none"):
            out.pop(k, None)
    return out


def validate_person_simple(person: Dict[str, str]) -> List[str]:
    """Very light validation suitable for a prototype."""
    errs: List[str] = []
    if not isinstance(person, dict):
        return ["person must be an object"]

    cnp = str(person.get("cnp") or "").strip()
    if cnp and not re.fullmatch(r"\d{13}", cnp):
        errs.append("cnp must be 13 digits")

    email = str(person.get("email") or "").strip()
    if email and not _EMAIL_RE.fullmatch(email):
        errs.append("email is invalid")

    tel = str(person.get("telefon") or "").strip()
    if tel and not re.fullmatch(r"0\d{9}", tel):
        errs.append("telefon must look like 0XXXXXXXXX")

    return errs

def extract_entities(raw: str) -> Dict[str, object]:
    """
    Extract structured entities from OCR text.

    Prototype rules:
    - person fields come from extract_person_fields()
    - address is kept as raw string (if found)
    - warnings list is best-effort
    """
    person = extract_person_fields(raw or "")
    warnings: List[str] = []

    if "cnp" not in person:
        warnings.append("missing_cnp")
    if "nume" not in person or "prenume" not in person:
        warnings.append("missing_name")

    return {
        "person": person,
        "address": {"raw": person.get("adresa") if isinstance(person, dict) else None},
        "warnings": warnings,
        "meta": {"parser": "regex_v1"}
    }