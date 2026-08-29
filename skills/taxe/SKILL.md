---
name: taxe
domain: tax
description: Taxe si impozite locale - informatii despre plata, documente necesare si depunerea declaratiilor.
language: ro
priority: 0
triggers: [impozit, taxe locale, taxa locala, plata impozit, impozite, declaratie fiscala, rol fiscal]
tools: [get_checklist, check_missing_documents, validate_document, get_fees, create_case, kb_search]
fallback_reply: Pentru plata taxelor si impozitelor locale ai nevoie de urmatoarele documente:
fallback_tool: get_checklist
fallback_args: {"procedure": "taxe"}
---

# Procedura: Taxe si impozite locale

Acest domeniu este un schelet de demonstratie: fluxul complet de plata online nu
este implementat in prototip. Fii explicit cu cetateanul despre ce se poate face
aici si ce necesita deplasare la ghiseu.

## Pasul 1 — Documentele necesare

Apeleaza `get_checklist` cu `procedure="taxe"`. Verifica documentele incarcate
cu `validate_document`.

## Pasul 2 — Suma de plata

Apeleaza `get_fees` cu `procedure="taxe"`. Daca informatia nu exista in
configuratie, spune sincer ca suma se afla de la ghiseu sau din rolul fiscal —
nu estima si nu inventa valori.

## Pasul 3 — Depunerea

Apeleaza `create_case` cu `procedure="taxe"` dupa ce dosarul este complet.

## Note

Pentru intrebari despre termene de plata, bonificatii sau majorari de intarziere
foloseste `kb_search` si citeaza sursa.
