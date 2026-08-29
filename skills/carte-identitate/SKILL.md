---
name: carte-identitate
domain: ci
description: Eliberarea sau reinnoirea cartii de identitate (CEI/CIS/VR) - eligibilitate, acte necesare, programare, taxe.
language: ro
priority: 0
triggers: [buletin, carte de identitate, act de identitate, cartea de identitate, eliberare ci, ci expirat, schimbare domiciliu]
tools: [get_checklist, check_missing_documents, validate_document, list_uploaded_documents, get_eligibility_rules, get_fees, list_slots, reserve_slot, create_case]
fallback_reply: Pentru cartea de identitate ai nevoie de urmatoarele documente:
fallback_tool: get_checklist
fallback_args: {"procedure": "ci"}
---

# Procedura: Carte de identitate

Ghideaza cetateanul pas cu pas. Nu sari pasii si nu enumera acte din memorie —
lista vine intotdeauna din `get_checklist`.

## Pasul 1 — Stabileste motivul (eligibilitatea)

Intreaba de ce solicita actul si mapeaza pe unul din motivele returnate de
`get_eligibility_rules`:

- `EXP_60` — cartea de identitate expira in cel mult 60 de zile sau a expirat
- `AGE_14` — prima carte de identitate, la implinirea varstei de 14 ani
- `CHANGE_NAME` — schimbare de nume
- `CHANGE_ADDR` — schimbare de domiciliu / resedinta (viza de flotant)
- `LOSS` — pierdere, furt sau deteriorare

## Pasul 2 — Stabileste tipul actului

- `CEI` — carte electronica de identitate (programarea se face prin HUB-ul MAI)
- `CIS` — carte de identitate simpla (flux local, la primarie)
- `VR` — viza de resedinta

Daca cetateanul nu stie ce tip ii trebuie, explica diferenta pe scurt si
recomanda `CEI` ca varianta implicita.

## Pasul 3 — Documentele necesare

Apeleaza `get_checklist` cu `procedure="ci"`, plus `app_type` si
`eligibility_reason` daca le cunosti — lista se modifica in functie de acestea
(de exemplu `LOSS` adauga dovada de la politie).

Pentru fiecare document incarcat, verifica-l cu `validate_document`. Unele
documente au termen de valabilitate; daca tool-ul raspunde `valid=false`,
comunica exact motivul returnat si cere documentul corect. Nu accepta un
document pe care tool-ul l-a respins.

Foloseste `list_uploaded_documents` ca sa vezi ce a incarcat deja cetateanul in
sesiunea curenta, si `check_missing_documents` ca sa stii ce mai lipseste.

## Pasul 4 — Taxa

Apeleaza `get_fees` pentru costul aferent tipului ales. Prima eliberare de CEI
poate fi gratuita — nu presupune, verifica.

## Pasul 5 — Programarea

- pentru `CEI`: `list_slots` cu `service="hub"`
- pentru `CIS`/`VR`: fluxul este local, la ghiseul primariei

Prezinta intervalele disponibile si rezerva doar intervalul ales explicit de
cetatean, cu `reserve_slot`.

## Pasul 6 — Depunerea dosarului

Apeleaza `create_case` doar dupa ce `check_missing_documents` returneaza
`complete=true`. Daca `create_case` raspunde `created=false`, spune ce lipseste;
nu afirma niciodata ca dosarul a fost depus in acest caz.
