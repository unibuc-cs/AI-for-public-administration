# Repository Guidelines

## Project Structure & Module Organization
- `main.py` is the FastAPI entry point and mounts UI + API routes.
- `agents/` holds the orchestration graph and agent implementations (entry, CI, social, scheduling, operator, etc.).
- `services/` contains mock external services for HUB/local APIs.
- `templates/` and `static/` serve the chat/operator UIs and upload assets.
- `kb/` stores RAG knowledge inputs (e.g., `procedure.json`).
- `tests/` currently contains manual HTTP request fixtures (`.http`).
- `Doc/` holds project docs and assets.

## Build, Test, and Development Commands
- Create a venv and install deps:
  ```bash
  python -m venv .venv
  .venv\Scripts\activate
  pip install -r requirements.txt
  ```
- Run the app in mounted mode (single process):
  ```bash
  set RUN_MODE=mounted
  uvicorn main:app --reload --port 8000
  ```
- Run in split mode (multiple processes):
  ```bash
  set RUN_MODE=split
  uvicorn services.cei_hub_mock:app --reload --port 8001
  uvicorn services.primarie_local_mock:app --reload --port 8002
  uvicorn main:app --reload --port 8000
  ```
- Optional config lives in `.env` (e.g., `RUN_MODE`, `OPENAI_API_KEY`, `HUB_URL`, `LOCAL_URL`).

## Coding Style & Naming Conventions
- Use 4-space indentation and PEP 8 conventions.
- Prefer `snake_case` for functions/modules and `CapWords` for classes.
- Keep imports grouped: standard library, third-party, then local.
- No formatter/linter is enforced; keep changes minimal and consistent with nearby files.

## Testing Guidelines
- No automated test runner is configured. `tests/.http` is used for manual endpoint checks.
- If you add automated tests, place them in `tests/` as `test_*.py` and document the runner in `README.md`.

## Commit & Pull Request Guidelines
- Git history shows short, informal subjects; there is no enforced convention.
- Use concise, imperative subjects (e.g., "Add CI agent scheduling").
- PRs should include a clear description, steps to run/verify, and screenshots for UI changes in `templates/`.

## Security & Data Notes
- Do not commit secrets; keep them in `.env`.
- SQLite data lives in `mcp_demo.db` at the repo root; delete it to reset local state.
