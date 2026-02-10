# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Legal document analysis system for TJPR (Tribunal de Justiça do Paraná) that automates admissibility review of special appeals (Recurso Especial/Extraordinário). The system extracts data from legal PDFs, analyzes them using GPT-4o, and generates formal decision briefs.

**Stack:** Python 3.11+, OpenAI API (GPT-4o), PyMuPDF + pdfplumber, Pydantic, pytest

## Core Architecture

**3-Stage Sequential Pipeline:**
1. **Etapa 1** (`etapa1.py`): Extract structured data from appeal petition (process number, parties, legal provisions violated, etc.)
2. **Etapa 2** (`etapa2.py`): Thematic analysis of the lower court decision (acórdão), identifying legal themes, precedents, and procedural obstacles
3. **Etapa 3** (`etapa3.py`): Generate formatted admissibility brief with cross-validation to prevent hallucination

**Orchestration:** `pipeline.py` coordinates the full flow with checkpoint/recovery support via `state_manager.py`.

**PDF Processing:** `pdf_processor.py` uses PyMuPDF as primary engine with automatic pdfplumber fallback for scanned/problematic PDFs.

**Document Classification:** `classifier.py` automatically distinguishes between appeal petitions and court decisions using heuristics + LLM fallback.

**LLM Integration:** `llm_client.py` handles OpenAI API calls with exponential backoff retry for rate limits, token tracking, and timeout management.

## Key Design Decisions

### External Prompt Architecture
- Main AI instructions live in `prompts/SYSTEM_PROMPT.md` (not in code)
- **Rationale:** Enables rapid prompt iteration without code changes or redeployment
- The prompt is loaded via `prompt_loader.py` with caching and hot-reload support
- When updating prompts: increment version in SYSTEM_PROMPT.md, test with real cases, document changes in PR

### Anti-Hallucination Strategy
- Temperature fixed at 0.1 (conservative outputs)
- Cross-validation between stages: Etapa 3 verifies data from Etapa 1 & 2 matches
- Literal transcriptions from source documents verified via substring search
- Legal citation validation: only allowed precedents/súmulas from predefined lists (STJ: 5, 7, 13, 83, 126, 211, 518; STF: 279-284, 356, 735)

### State Management & Recovery
- `state_manager.py` serializes full pipeline state to JSON checkpoints
- Enables recovery from interruptions (API failures, timeouts, user abort)
- CLI commands: `status` (show checkpoints), `limpar` (clear checkpoints), `processar --continuar` (resume)
- State includes: document metadata, all stage results, tokens consumed, timestamps

### Data Models
- All data structures in `models.py` using Pydantic for validation
- Key models: `DocumentoEntrada`, `ResultadoEtapa1/2/3`, `EstadoPipeline`
- Enforces type safety and prevents malformed data propagation

## Common Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
cp .env.example .env  # Then edit with your OPENAI_API_KEY

# Run pipeline
python -m src.main processar recurso.pdf acordao.pdf
python -m src.main processar *.pdf --formato docx --verbose
python -m src.main processar *.pdf --continuar  # Resume from checkpoint

# Testing
python -m pytest -q                    # Quick run
python -m pytest --cov=src             # With coverage
python -m pytest tests/test_pipeline.py -v  # Single module
python -m pytest -k "test_extraction"  # Filter by name

# Checkpoint management
python -m src.main status
python -m src.main limpar

# Run web API (if implemented)
python -m src.web_app
```

## Module Responsibilities

- `main.py`: CLI entrypoint with argparse interface
- `config.py`: Load environment variables, validate API key presence, define constants
- `pipeline.py`: Orchestrates document classification → Etapa 1 → 2 → 3, manages state
- `etapa1.py/2.py/3.py`: Implement each analysis stage with LLM calls and response parsing
- `pdf_processor.py`: Text extraction with PyMuPDF + pdfplumber fallback, handles corrupted/scanned PDFs
- `classifier.py`: Document type detection (RECURSO vs ACORDAO) using pattern matching + LLM
- `llm_client.py`: Reusable OpenAI client with retry logic, token tracking, timeout handling
- `prompt_loader.py`: Load and parse `SYSTEM_PROMPT.md`, extract stage-specific sections
- `output_formatter.py`: Generate `.md` and `.docx` output files with legal formatting
- `state_manager.py`: Serialize/deserialize pipeline state for checkpoints
- `models.py`: Pydantic data models for type safety and validation

## Coding Conventions

- **Language:** Code/variables/comments in English, user-facing messages in Portuguese
- **Type hints:** Mandatory on all functions (enforced by convention, consider mypy in CI)
- **Style:** PEP 8 (4-space indent, snake_case functions/vars, PascalCase classes, UPPER_CASE constants)
- **Logging:** Use `logging` module, not `print` (except CLI display via `rich`)
- **Error handling:** Explicit try/except with clear user messages for common failures (invalid API key, PDF corruption, rate limits)
- **Commits:** Conventional Commits format (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`)

## Testing Strategy

- Framework: pytest + pytest-cov
- Test files: `tests/test_*.py` mirroring `src/*.py` structure
- Fixtures: Representative PDFs in `tests/fixtures/` (valid, minimal, corrupted, scanned)
- Unit tests: Individual modules (PDF extraction, classification, parsing)
- Integration tests: Full pipeline with real LLM calls (mark as slow with `@pytest.mark.slow`)
- Target: >80% coverage for core logic (pipeline, etapas, parsers)
- Run full suite before PRs: `python -m pytest --cov=src`

## Output Structure

Generated in `outputs/` (or `--saida` override):

- `minuta_<processo>_<timestamp>.md` (or `.docx`): Final admissibility brief
- `auditoria_<processo>_<timestamp>.md`: Audit report (tokens used, validation warnings, timestamps)
- `.checkpoints/estado_<id>.json`: Serialized pipeline state for recovery

Checkpoint JSON structure:
```json
{
  "documentos_entrada": [{"filepath": "...", "tipo": "RECURSO", "num_paginas": 10}],
  "resultado_etapa1": {"numero_processo": "...", "recorrente": "...", ...},
  "resultado_etapa2": {"temas": [{"materia_controvertida": "...", ...}]},
  "resultado_etapa3": {"minuta_completa": "...", "decisao": "ADMITIDO"},
  "metadata": {"inicio": "...", "fim": "...", "total_tokens": 45000, ...}
}
```

## Environment Variables

Required in `.env`:
- `OPENAI_API_KEY`: OpenAI API key (mandatory)
- `OPENAI_MODEL`: Model name (default: `gpt-4o`)
- `TEMPERATURE`: LLM temperature (default: `0.1`)
- `MAX_TOKENS`: Max tokens per completion (default: `4096`)
- `LLM_TIMEOUT`: Request timeout in seconds (default: `120`)
- `LLM_MAX_RETRIES`: Retry attempts for transient errors (default: `3`)
- `LOG_LEVEL`: Logging verbosity (default: `INFO`)

## Prompt Workflow

1. Edit `prompts/SYSTEM_PROMPT.md` with instruction changes
2. Increment version number in prompt header
3. Test with at least 1 real case: `python -m src.main processar <test_files>`
4. Compare output quality vs. previous version
5. Run tests to check for regressions: `python -m pytest`
6. Document prompt changes in PR description

## Token & Cost Management

- All LLM calls tracked via `llm_client.py`
- Token usage logged: `prompt_tokens`, `completion_tokens`, `total_tokens`
- Audit report includes cost estimate based on GPT-4o pricing
- Use `tiktoken` for pre-call estimation to avoid context limit surprises
- Stage 1 typically uses ~2-5k tokens, Stage 2: ~5-10k, Stage 3: ~8-15k (varies with case complexity)

## Common Pitfalls

- **PDF extraction fails:** PDFs may be scanned without OCR; pdfplumber fallback may not help. Future: integrate Tesseract OCR.
- **Context limit exceeded:** Large case files (>100 pages) may need chunking. Check `pdf_processor.py` for current limits.
- **Hallucinated legal citations:** Validate all súmulas/precedents cited in Etapa 3 against allowed lists in `etapa2.py`.
- **Rate limits:** OpenAI API has rate limits; `llm_client.py` retries with exponential backoff, but may still fail under sustained load.
- **Temperature changes:** Increasing temperature above 0.1 may improve creativity but risks hallucination; test carefully.

## Integration Points

- **CLI:** Primary interface via `main.py`
- **Web API:** `web_app.py` provides Flask endpoint for external integrations (e.g., n8n workflows)
- **State files:** Can be parsed by external tools for monitoring/auditing
- **Output files:** `.md` format easily converted to other formats via pandoc
