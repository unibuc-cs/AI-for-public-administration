# AI Public Administration Prototype (Romanian Workflows)

This repository contains a **prototype** implementation of a step-driven, agent-oriented architecture for Romanian administrative workflows. The prototype is intended as a **research artifact** to illustrate how conversational assistance can be embedded within **explicit workflow semantics**, **role-aware authorization**, and **guarded execution boundaries**.

## What is implemented in this prototype

The current version instantiates the architecture in **three workflows**:

- **Identity Card (CI)**: intake confirmation, document checklist, document intake, OCR-assisted extraction, appointment/scheduling guidance, operator handoff and status updates.
- **Social Aid**: eligibility questionnaire guidance, evidence collection, case creation, operator validation, decision communication.
- **Local Tax Payment**: payment intent, obligation retrieval, confirmation, receipt generation.

These workflows **reuse shared components** (routing, case/task handling, authorization checks, document intake/processing hooks) while keeping **domain logic** inside dedicated workflow agents.

## Architectural summary

The prototype follows a separation-of-concerns pattern aligned with the paper:

- **Reasoning (agents):** agents choose the next admissible interaction based on the current workflow/case context.
- **Rendering (UI templates):** the frontend is treated as a deterministic renderer of structured interaction outputs.
- **Execution (tools/endpoints):** state-changing operations are executed through protected endpoints and tool functions with explicit permission checks.

In code, the interaction layer is surfaced through the `/api/chat` endpoint, which returns a `reply` and optional `steps` to drive UI behavior.

## Agents included

The orchestrator runs an agent graph with the following agents:

- **EntryAgent**: initial greeting and session initialization.
- **RouterAgent**: selects the workflow domain (CI / Social Aid / Tax / Operator view) using intent signals.
- **CiAgent**: identity card workflow logic.
- **SocialAidAgent**: social aid workflow logic.
- **TaxPaymentAgent**: local tax payment workflow logic.
- **OperatorAgent**: operator-facing flows (task listing/claim/complete).
- **DocOcrAgent**: local OCR/document extraction support (prototype hooks).
- **LegalGovAgent**: retrieval-augmented legal/procedural assistance (prototype hooks).

The design is extensible: additional agents and external tool servers can be integrated behind the same `/api/chat` interaction contract.

## Running the prototype

### 1) Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
```

### 2) Start the server

```bash
uvicorn main:app --reload
```

- Public chat endpoint: `POST /api/chat`
- Login/logout: `POST /login`, `POST /logout`
- Operator endpoints (protected): `/operator/*`

## Tests

This repository includes a small **JSON-driven test suite** intended to be:
- simple to run locally,
- easy to extend,
- aligned with paper claims (routing, guarded endpoints, basic separation properties).

### Run

```bash
python -m tests.run_json_tests --spec tests/tests.json
```

### Test spec fields (high level)

Each test in `tests/tests.json` includes:

- `id`, `name`
- `request`: `method`, `path`, optional `json` body
  - `auth`: `{username, password}` performs `/login` and reuses the session cookie
  - `sequence`: list of calls for multi-turn tests
- `expect`: assertions such as
  - `status`: expected HTTP code
  - `json_has_keys`: required top-level keys
  - `json_path_equals`: dotted-path equality checks (e.g., `state.current_domain`)
  - `json_path_contains`: string containment checks
  - `set_cookie_contains`: checks authentication cookie behavior

### Extending

Add new cases to `tests/tests.json`. The runner supports referencing values from the **previous** response using `"@prev.<field>"`.

## Repository status

This is a research prototype:
- it is **not deployed** in production environments;
- workflows and integrations are representative, not exhaustive;
- evaluation artifacts are provided as runnable tests and structured logs.

