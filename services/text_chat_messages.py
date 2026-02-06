# text_chat_messages.py
# Supporting ro and eng, but easily extensible to more languages in the future.
# Centralized message templates with formatting.
from __future__ import annotations

from typing import Any, Dict

DEFAULT_LANG = "ro"  # ro = Romanian (ASCII-only), en = English

MESSAGES: Dict[str, Dict[str, str]] = {
    "choose_lang": {
        "ro": "Preferi Romana sau English? Raspunde RO sau EN.",
        "en": "Do you prefer Romanian or English? Reply RO or EN.",
    },
    "lang_set_ro": {
        "ro": "Ok. Voi folosi Romana (fara diacritice te rog).",
        "en": "Ok. I will use Romanian (ASCII-only).",
    },
    "lang_set_en": {
        "ro": "Ok. Voi folosi English.",
        "en": "Ok. I will use English.",
    },

    "upload_recognized": {
        "ro": "Am recunoscut: {docs}.",
        "en": "Recognized: {docs}.",
    },
    "upload_unrecognized": {
        "ro": "Nu am putut recunoaste tipul documentului. Incearca o imagine mai clara sau seteaza DocHint.",
        "en": "Could not recognize document kind. Try a clearer image or set DocHint.",
    },

    "ocr_found_fields": {
        "ro": "Am extras urmatoarele campuri din documente:\n{preview}\n\nVrei sa le completez automat in formular? Raspunde DA sau NU.",
        "en": "I extracted these fields from your documents:\n{preview}\n\nApply them to the form? Reply YES or NO.",
    },
    "ocr_no_fields": {
        "ro": "Am rulat OCR, dar nu am extras campuri utile. Poti completa manual.",
        "en": "OCR ran but no usable fields were found. You can fill manually.",
    },
    "autofill_applied": {
        "ro": "Ok. Am completat campurile in formular.",
        "en": "Ok. I applied the fields to the form.",
    },
    "autofill_ignored": {
        "ro": "Ok. Nu aplic valorile OCR.",
        "en": "Ok. I will not apply OCR values.",
    },

    "sched_help": {
        "ro": "Pentru programare: alege locatia, apoi slotul, apoi apasa Use this slot.",
        "en": "For scheduling: select location, then slot, then click Use this slot.",
    },
}

# Normalize various language inputs to a standard code. Default to DEFAULT_LANG if unrecognized.
def _normalize_lang(x: str) -> str:
    x = (x or "").strip().lower()
    if x in ("ro", "romana", "romanian"):
        return "ro"
    if x in ("en", "english"):
        return "en"
    return DEFAULT_LANG

# Get the language code from the app context, normalizing it and defaulting to DEFAULT_LANG if not set or unrecognized.
def get_lang(app: Any) -> str:
    if isinstance(app, dict):
        return _normalize_lang(app.get("lang") or DEFAULT_LANG)
    return DEFAULT_LANG

# Translate a message key to the appropriate language, applying formatting if needed.
def translate_msg(app: Any, key: str, **kwargs) -> str:
    lang = get_lang(app)
    table = MESSAGES.get(key) or {}
    template = table.get(lang) or table.get(DEFAULT_LANG) or ""
    try:
        return template.format(**kwargs)
    except Exception:
        # never crash due to formatting in prototype
        return template
