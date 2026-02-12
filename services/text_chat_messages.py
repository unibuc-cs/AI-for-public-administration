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

    "title_upload": {
        "ro": "Upload",
        "en": "Upload",
    },

    "title_ocr": {
        "ro": "OCR",
        "en": "OCR",
    },

    "title_scheduling": {
        "ro": "Programare",
        "en": "Scheduling",
    },

    "title_case": {
        "ro": "Caz",
        "en": "Case",
    },

    "title_hubgov": {
        "ro": "HubGov",
        "en": "HubGov",
    },

    "title_legal": {
        "ro": "Legal",
        "en": "Legal",
    },

    "ocr_toast_updated": {
        "ro": "Am actualizat entitatile OCR pentru documentele incarcate.",
        "en": "OCR entities updated for uploaded documents.",
    },

    "sched_reply": {
        "ro": "Ok. Te-am ghidat catre pasul de programare din formular.",
        "en": "Ok. I guided you to the scheduling step in the form.",
    },

    "router_ask_need": {
        "ro": "Spune-mi cu ce te pot ajuta (CI, ajutor social, programare, intrebari legale).",
        "en": "Tell me what you need help with (ID card, social aid, scheduling, legal questions).",
    },

    "entry_help": {
        "ro": "Pot ajuta cu: carte de identitate, ajutor social, programare, sau intrebari legale. Spune-mi ce vrei sa faci.",
        "en": "I can help with: ID card, social aid, scheduling, or legal questions. Tell me what you want to do.",
    },

    "entry_nav_link": {
        "ro": "{label}: {url}",
        "en": "{label}: {url}",
    },

    "social_detect_uploads": {
        "ro": "Am detectat documente incarcate. Verific si incerc sa completez automat.",
        "en": "I detected uploaded documents. I will check and try to autofill.",
    },

    "social_step1": {
        "ro": "Step 1/3: Selecteaza un slot in pagina (Slots) si apasa Use this slot. Dupa asta continui cu eligibilitate si documente.",
        "en": "Step 1/3: Select a slot in the page (Slots) and click Use this slot. Then we continue with eligibility and documents.",
    },

    "social_step2": {
        "ro": "Step 2/3: Alege tipul cererii si motivul/eligibilitatea. Dupa asta continui cu documente si confirmare.",
        "en": "Step 2/3: Choose request type and eligibility reason. Then we continue with documents and confirmation.",
    },

    "social_step3": {
        "ro": "Step 3/3: Incarca documentele necesare. Cand esti gata, scrie CONFIRM pentru a crea cererea.",
        "en": "Step 3/3: Upload required documents. When ready, type CONFIRM to create the request.",
    },

    "social_missing_fields_toast": {
        "ro": "Completeaza campurile lipsa.",
        "en": "Please fill the missing fields.",
    },

    "social_missing_docs": {
        "ro": "Lipsesc documente: {docs}. Incarca-le in pagina.",
        "en": "Missing documents: {docs}. Please upload them in the page.",
    },

    "social_ready_create": {
        "ro": "Perfect. Am toate datele si documentele necesare. Creez cererea.",
        "en": "Great. I have all required data and documents. Creating the request.",
    },

    "operator_found_tasks": {
        "ro": "Am gasit {n} task-uri.",
        "en": "Found {n} tasks.",
    },

    "operator_found_cases": {
        "ro": "Am gasit {n} cazuri.",
        "en": "Found {n} cases.",
    },

    "operator_task_claimed": {
        "ro": "Task {id} a fost preluat.",
        "en": "Task {id} claimed.",
    },

    "operator_task_completed": {
        "ro": "Task {id} a fost marcat ca rezolvat.",
        "en": "Task {id} completed.",
    },

    "operator_case_updated": {
        "ro": "Cazul {id} a fost actualizat: {status}.",
        "en": "Case {id} updated: {status}.",
    },

    "operator_help": {
        "ro": "Operator: poti cere lista de task-uri, lista de cazuri, sau actualizari pentru un caz.",
        "en": "Operator: you can ask for task list, case list, or updates for a case.",
    },

    "case_created": {
        "ro": "Caz {id} creat.",
        "en": "Case {id} created.",
    },

    "hubgov_placeholder": {
        "ro": "HubGov este placeholder acum. In viitor va apela serviciile CEI hub.",
        "en": "HubGov is a placeholder for now. Later it will call CEI hub services.",
    },

    "legalgov_placeholder": {
        "ro": "Agentul legal este placeholder acum. Pune intrebarea ta si voi raspunde cand e integrat.",
        "en": "Legal agent is a placeholder for now. Ask your question and I will answer when integrated.",
    },

    "greet_entry": {
      "ro": "Salut! Cu ce te pot ajuta? (CI, Ajutor social, Programare, Legal)",
      "en": "Hi! How can I help? (ID card, Social aid, Scheduling, Legal)",
    },
    "greet_ci": {
      "ro": "Salut! Te ajut cu cererea pentru carte de identitate.",
      "en": "Hi! I can help with the ID card request.",
    },
    "greet_social": {
      "ro": "Salut! Te ajut cu cererea pentru ajutor social.",
      "en": "Hi! I can help with the social aid request.",
    },
    "greet_operator": {
      "ro": "Salut! Spune-mi ce vrei sa faci ca operator.",
      "en": "Hi! Tell me what you want to do as an operator.",
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
