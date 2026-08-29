---
name: documente
domain: documents
description: Incarcarea si verificarea documentelor - ce formate sunt acceptate, ce a fost recunoscut prin OCR, de ce a fost respins un document.
language: ro
priority: 1
sets_domain: false
triggers: [incarc document, cum incarc, incarcare acte, poza la act, scanez, scanare act, fisier incarcat, upload]
tools: [list_uploaded_documents, validate_document, check_missing_documents]
fallback_reply: Poti incarca documentele din pagina serviciului. Sunt acceptate imagini clare (JPG/PNG) sau PDF; dupa incarcare verific automat ce document este si daca este valabil.
---

# Incarcarea documentelor

Skill consultativ, folosit impreuna cu procedura in lucru — nu inlocuieste
procedura curenta.

## Ce sa faci

1. `list_uploaded_documents` arata ce a fost recunoscut prin OCR pentru sesiunea
   curenta. Recunoasterea automata poate gresi — cere confirmarea cetateanului
   inainte sa te bazezi pe ea.
2. `validate_document` decide daca un document este acceptabil. Rezultatul acestui
   tool este singurul care conteaza:
   - `unknown_kind` — tipul documentului nu este recunoscut
   - `issue_date_required` — institutia cere un document recent; intreaba data emiterii
   - `doc_too_old` — documentul depaseste termenul de valabilitate acceptat
   - `bad_issue_date` — data nu a putut fi interpretata; cere formatul AAAA-LL-ZZ
3. `check_missing_documents` arata ce mai lipseste din dosar.

## Reguli

- Nu declara un document valabil daca `validate_document` a returnat `valid=false`.
- Cand un document este respins, spune motivul exact returnat de tool si ce
  trebuie sa aduca cetateanul in loc.
- Datele extrase automat (nume, CNP, adresa) se completeaza in formular **doar**
  dupa confirmarea explicita a cetateanului.

## Sfaturi practice pentru cetatean

- fotografiaza documentul intreg, pe fundal contrastant, fara blitz direct
- pentru carti de identitate, ambele fete
- text lizibil, fara degete peste informatii
