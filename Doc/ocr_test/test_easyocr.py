import sys

import easyocr
import cv2

import re
from typing import List, Dict, Any, Tuple, Optional


def normalize_line(s: str) -> str:
    # Normalize common OCR oddities (optional)
    s = s.strip()
    s = s.replace("ﬁ", "fi").replace("’", "'")
    return s


def from_easyocr_results(results: List[Tuple], min_conf: float = 0.4) -> List[str]:
    """
    Convert EasyOCR results [(bbox, text, conf), ...] into a list of text lines.
    """
    lines = []
    for _, text, conf in results:
        if conf is None or conf >= min_conf:
            lines.append(normalize_line(text))
    return lines


def extract_lines_from_image(img_path: str, verbose: bool = False) -> List[str]:
    """
    Extract text lines from image using EasyOCR.
    :param img_path:
    :return: list of tuples (bbox, text, conf)
    """
    img = cv2.imread(img_path)

    # Upscale helps a lot for small fonts
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    reader = easyocr.Reader(
        ['en'],        # 'en' is usually best for Romanian CI (Latin uppercase, few diacritics)
        gpu=False
    )

    results = reader.readtext(img)

    filtered_results = from_easyocr_results(results, min_conf=0.4)

    if verbose:
        print("OCR Results (conf >= 0.4):")
        print("==========================")
        for bbox, text, conf in results:
            if conf >= 0.4:
                print(f"{conf:.2f}  {text}")
        print("==========================")


    return filtered_results






def extract_fields(lines: List[str]) -> Dict[str, Any]:
    """
    Parse OCR lines into structured fields.
    """

    LABEL_LASTNAME = re.compile(r"\bNume\b|Last\s*name|Nom", re.IGNORECASE)
    LABEL_FIRSTNAME = re.compile(r"\bPrenume\b|First\s*name|Prenom", re.IGNORECASE)
    LABEL_CNP = re.compile(r"\bCNP\b", re.IGNORECASE)
    LABEL_ADDRESS = re.compile(r"\bDomiciliu\b|Address|Adresse", re.IGNORECASE)
    LABEL_SEX = re.compile(r"\bSex\b|Sexe", re.IGNORECASE)

    # Labels that often appear AFTER address; used to stop address capture
    # Only "strong" section headers that should NOT appear inside an address line
    STOP_SECTION = re.compile(
        r"(Valabilitate|Validity|Validite|"
        r"Emisa|Issued|"
        r"Cetatenie|Nationality|Nationalite|"
        r"Loc\s+nastere|Place\s+of\s+birth|Lieu\s+de\s+naissance|"
        r"SERIA\b|"
        r"IDROU|R0U|ROU\b)",
        re.IGNORECASE
    )

    CNP_RE = re.compile(r"\b\d{13}\b")
    SEX_RE = re.compile(r"^[MF]$")


    lines = [normalize_line(x) for x in lines if normalize_line(x)]
    out: Dict[str, Any] = {
        "last_name": None,
        "first_name_raw": None,
        "first_names": [],
        "cnp": None,
        "sex": None,
        "address_lines": [],
        "address": None,
    }

    # --- 1) CNP: anywhere in the text ---
    for s in lines:
        m = CNP_RE.search(s)
        if m:
            out["cnp"] = m.group(0)
            break

    # --- 2) Last name + First name: take the line immediately after labels ---
    def next_non_label_value(start_idx: int) -> Optional[str]:
        # Find next line that looks like a value (not another label)
        for j in range(start_idx + 1, min(start_idx + 6, len(lines))):
            cand = lines[j].strip()
            if not cand:
                continue
            # skip if it looks like a label line
            if LABEL_LASTNAME.search(cand) or LABEL_FIRSTNAME.search(cand) or LABEL_ADDRESS.search(cand) or LABEL_SEX.search(cand) or LABEL_CNP.search(cand):
                continue
            # skip obvious MRZ line
            if "<" in cand and len(cand) > 20:
                continue
            return cand
        return None

    for i, s in enumerate(lines):
        if out["last_name"] is None and LABEL_LASTNAME.search(s):
            val = next_non_label_value(i)
            if val:
                out["last_name"] = val
        if out["first_name_raw"] is None and LABEL_FIRSTNAME.search(s):
            val = next_non_label_value(i)
            if val:
                out["first_name_raw"] = val

    # Split first name(s) on hyphen if present
    if out["first_name_raw"]:
        parts = [p.strip() for p in re.split(r"[-–]", out["first_name_raw"]) if p.strip()]
        out["first_names"] = parts

    # --- 3) Sex: first standalone M/F after the Sex label ---
    for i, s in enumerate(lines):
        if LABEL_SEX.search(s):
            for j in range(i + 1, min(i + 8, len(lines))):
                cand = lines[j].strip()
                # sometimes OCR returns 'M' on its own line, sometimes embedded
                if SEX_RE.match(cand):
                    out["sex"] = cand
                    break
                m = re.search(r"\b([MF])\b", cand)
                if m:
                    out["sex"] = m.group(1)
                    break
            if out["sex"]:
                break

    # --- 4) address: capture until next section ---
    addr_lines: List[str] = []
    for i, s in enumerate(lines):
        if LABEL_ADDRESS.search(s):
            for j in range(i + 1, len(lines)):
                cand = lines[j].strip()
                if not cand:
                    continue

                # Stop if we hit MRZ
                if "<" in cand and len(cand) > 20:
                    break

                # Stop if we hit another field/section label
                if STOP_SECTION.search(cand):
                    break
                if any(rx.search(cand) for rx in [LABEL_LASTNAME, LABEL_FIRSTNAME, LABEL_SEX, LABEL_CNP]):
                    break

                # Heuristic: avoid grabbing stray single letters like "B"
                # Keep "B" only if it looks like apartment/building notation (rare) otherwise skip.
                if re.fullmatch(r"[A-Z]", cand) and cand not in {"A", "B"}:
                    continue
                if re.fullmatch(r"[A-Z]", cand) and cand in {"A", "B"}:
                    # keep only if we already have address content (likely "Bl. B" etc.)
                    if not addr_lines:
                        continue

                addr_lines.append(cand)

            break

    out["address_lines"] = addr_lines
    if addr_lines:
        out["address"] = ", ".join(addr_lines)

    return out


if __name__ == "__main__":

    ocr_lines = extract_lines_from_image(sys.argv[1])

    fields = extract_fields(ocr_lines)

    # Print safely (mask CNP in debug)
    cnp_masked = None
    if fields["cnp"]:
        cnp_masked = fields["cnp"][:3] + "*" * (len(fields["cnp"]) - 3)

    print("Last name:", fields["last_name"])
    print("First names:", fields["first_names"])  # ["CIPRIAN", "IONUT"]
    print("CNP (masked):", cnp_masked)
    print("Sex:", fields["sex"])
    print("Address lines:", fields["address_lines"])
    print("Address:", fields["address"])
