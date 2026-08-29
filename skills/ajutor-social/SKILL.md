---
name: ajutor-social
domain: social
description: Cerere de ajutor social / venit minim de incluziune - acte necesare, programare la asistenta sociala, depunere dosar.
language: ro
priority: 0
triggers: [ajutor social, venit minim, vmi, beneficii sociale, asistenta sociala, ajutor de incalzire, alocatie]
tools: [get_checklist, check_missing_documents, validate_document, list_uploaded_documents, list_slots, reserve_slot, create_case]
fallback_reply: Pentru dosarul de ajutor social ai nevoie de urmatoarele documente:
fallback_tool: get_checklist
fallback_args: {"procedure": "social"}
---

# Procedura: Ajutor social

## Pasul 1 — Documentele necesare

Apeleaza `get_checklist` cu `procedure="social"`. Explica pe scurt la ce
foloseste fiecare document; nu cere acte care nu apar in lista returnata.

Verifica fiecare document incarcat cu `validate_document` si urmareste ce mai
lipseste cu `check_missing_documents`.

## Pasul 2 — Programarea la asistenta sociala

Programarile pentru ajutor social se fac local: `list_slots` cu
`service="local"`. Rezerva cu `reserve_slot` doar intervalul ales de cetatean.

## Pasul 3 — Depunerea dosarului

Apeleaza `create_case` cu `procedure="social"` doar dupa ce dosarul este
complet. Daca tool-ul refuza, comunica exact ce lipseste.

## Note

Daca cetateanul intreaba despre criterii de venit sau despre baza legala,
foloseste `kb_search` si citeaza sursa — nu raspunde din memorie.
