# Repository Guidelines

## Project Structure & Module Organization
Core code lives in `src/`:
- `main.py`: CLI entrypoint (`processar`, `status`, `limpar`)
- `pipeline.py`: orchestrates Etapas 1-3
- `etapa1.py`, `etapa2.py`, `etapa3.py`: legal analysis stages
- `pdf_processor.py`, `classifier.py`, `llm_client.py`: ingestion + AI integration
- `output_formatter.py`: output generation (`.md` and `.docx`)

Tests are in `tests/` with fixtures under `tests/fixtures/`.  
Prompts are in `prompts/` (notably `SYSTEM_PROMPT.md`).  
Generated artifacts go to `outputs/`.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate`: create and activate venv.
- `pip install -r requirements.txt`: install dependencies.
- `python -m src.main processar arquivo1.pdf arquivo2.pdf --formato docx`: run full pipeline.
- `python -m src.main status`: list checkpoints.
- `python -m src.main limpar`: remove checkpoints.
- `python -m pytest -q`: run full test suite.
- `python -m pytest --cov=src`: run tests with coverage.

## Coding Style & Naming Conventions
- Python 3.11+ with mandatory type hints.
- Follow PEP 8 (4-space indentation, clear function names, small focused functions).
- Keep code/identifiers in English; user-facing messages and docs can be Portuguese.
- Use `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants.
- Prefer explicit error handling and `logging` over `print` in application modules.

## Testing Guidelines
- Framework: `pytest` (+ `pytest-cov`).
- Test files follow `tests/test_*.py`; test functions use `test_*`.
- Mirror source behavior by module (e.g., pipeline tests in `tests/test_pipeline.py`).
- Add fixtures for representative PDFs and edge cases (corrupted/invalid files).
- Run full tests before opening a PR.

## Commit & Pull Request Guidelines
- Use Conventional Commits (`feat:`, `fix:`, `refactor:`), as seen in history (e.g., `feat: scaffold project structure ...`).
- Keep commits focused and atomic; avoid mixing refactor + feature + test-only changes.
- PRs should include:
  - concise problem/solution summary
  - impacted files/modules
  - test evidence (command + result)
  - any checklist updates in `TASKS.md` when completing sprint tasks

## Security & Configuration Tips
- Never commit `.env` or real API keys.
- Start from `.env.example` and set `OPENAI_API_KEY`.
- Treat `outputs/` as generated content; do not store sensitive case data.
