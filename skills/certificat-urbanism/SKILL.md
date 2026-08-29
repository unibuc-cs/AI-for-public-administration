---
name: certificat-urbanism
domain: urbanism
description: Certificat de urbanism - acte necesare si depunerea cererii pentru informare privind regimul juridic, economic si tehnic al unui imobil.
language: ro
priority: 0
triggers: [certificat de urbanism, certificat urbanism, regim urbanistic, autorizatie de construire, urbanism, cadastru]
tools: [get_checklist, check_missing_documents, validate_document, create_case, kb_search]
fallback_reply: Pentru certificatul de urbanism ai nevoie de urmatoarele documente:
fallback_tool: get_checklist
fallback_args: {"procedure": "urbanism"}
---

# Procedura: Certificat de urbanism

Certificatul de urbanism este un act de informare: precizeaza regimul juridic,
economic si tehnic al imobilului. **Nu** este autorizatie de construire si nu da
dreptul de a executa lucrari — spune asta explicit daca cetateanul confunda cele
doua documente.

## Pasul 1 — Scopul cererii

Intreaba pentru ce este solicitat certificatul (informare, autorizatie de
construire, dezmembrare, vanzare). Scopul se trece in cerere si influenteaza
avizele cerute ulterior.

## Pasul 2 — Documentele necesare

Apeleaza `get_checklist` cu `procedure="urbanism"`. Verifica fiecare document
incarcat cu `validate_document` si urmareste ce lipseste cu
`check_missing_documents`.

## Pasul 3 — Depunerea

Apeleaza `create_case` cu `procedure="urbanism"` dupa ce dosarul este complet.

## Note

Termenele legale de eliberare si taxele difera intre primarii. Pentru orice
intrebare de acest tip foloseste `kb_search`; daca baza de cunostinte nu contine
raspunsul, indruma cetateanul catre ghiseul de urbanism — nu estima termene.
