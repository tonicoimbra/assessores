# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Assessor.AI** — Sistema de análise automatizada de recursos jurídicos (Recurso Especial e Extraordinário) do TJPR (Tribunal de Justiça do Paraná). O sistema recebe PDFs fracionados de petições recursais e acórdãos, classifica automaticamente cada documento, executa um pipeline sequencial de 3 etapas via OpenAI API (GPT-4.1) e produz uma minuta formal de decisão de admissibilidade.

**Contexto Jurídico:** O sistema analisa recursos judiciais destinados aos tribunais superiores (STJ/STF), verificando requisitos de admissibilidade conforme legislação processual civil brasileira. O output é uma minuta de decisão monocrática formatada segundo padrões do TJPR.

**Stack:** Python 3.11+, OpenAI API (GPT-4.1 / GPT-4.1-mini), PyMuPDF + pdfplumber, Pydantic, Flask, tiktoken, pytest

**LLM Providers:** OpenAI (default), OpenRouter, Google AI Studio (via env var `LLM_PROVIDER`)

**Documentação completa:** `docs/README.md` (índice) → `docs/visao-geral.md`, `docs/arquitetura.md`, `docs/padroes-desenvolvimento.md`, etc.

**Referências obrigatórias antes de mudanças estruturais:**
- `PRD.md` — requisitos, sprints e critérios de aceite
- `docs/README.md` — índice da documentação técnica
- `prompts/SYSTEM_PROMPT.md` — regras e comportamento do agente jurídico
- Em caso de conflito: priorize requisitos do `PRD.md` e mantenha consistência com a implementação existente.

## Core Architecture

**Pipeline Sequencial de 3 Etapas:**

```
PDFs (upload) → Extração de Texto → Classificação → Etapa 1 → 2 → 3 → Minuta Final
     │                │                    │              │    │    │         │
     ▼                ▼                    ▼              ▼    ▼    ▼         ▼
  Validação      PyMuPDF/            Heurística +     Recurso Acórdão Minuta  Markdown +
  de entrada     pdfplumber          LLM fallback     (OpenAI) (OpenAI)(OpenAI) DOCX
```

1. **Etapa 1** (`etapa1.py`): Extrai dados estruturados da petição recursal (nº processo, partes, dispositivos violados, permissivo constitucional, flags)
2. **Etapa 2** (`etapa2.py`): Análise temática do acórdão recorrido (matérias controvertidas, fundamentos, base vinculante, óbices/súmulas) — suporta processamento paralelo de temas
3. **Etapa 3** (`etapa3.py`): Gera minuta formatada de decisão de admissibilidade com validação cruzada anti-alucinação

**Orquestração:** `pipeline.py` coordena o fluxo completo com checkpoints de recuperação via `state_manager.py`.

## Module Responsibilities

### Core Pipeline
| Módulo | Responsabilidade |
|--------|------------------|
| `main.py` | Entrypoint CLI com argparse (`processar`, `status`, `limpar`) |
| `config.py` | Carregamento de `.env`, validação de API key, constantes e feature flags |
| `pipeline.py` | Orquestrador: classificação → Etapa 1 → 2 → 3, gestão de estado e métricas |
| `etapa1.py` | Análise da petição recursal com parsing estruturado da resposta LLM |
| `etapa2.py` | Análise temática do acórdão com validação de súmulas permitidas |
| `etapa3.py` | Geração da minuta com validação cruzada entre etapas |
| `models.py` | Modelos Pydantic: `DocumentoEntrada`, `ResultadoEtapa1/2/3`, `EstadoPipeline` |

### Ingestion & AI
| Módulo | Responsabilidade |
|--------|------------------|
| `pdf_processor.py` | Extração de texto com PyMuPDF + fallback pdfplumber; suporte OCR opcional (Tesseract) |
| `classifier.py` | Classificação automática (RECURSO vs ACORDÃO) via heurísticas textuais + LLM fallback; possui invariantes configuráveis e revisão manual |
| `llm_client.py` | Cliente LLM multi-provider reutilizável: retry com backoff exponencial, tracking de tokens, timeout |
| `prompt_loader.py` | Carregamento do prompt com cache, hot-reload e estratégia modular (`system_base.md` + `dev_etapa*.md`) ou legacy (`SYSTEM_PROMPT.md`) |
| `model_router.py` | Roteamento híbrido de modelos (GPT-4.1-mini para tarefas simples, GPT-4.1 para análise crítica) |
| `token_manager.py` | Gestão de budget de tokens, estimativa com tiktoken, chunking inteligente, rate limiting |
| `cache_manager.py` | Cache de respostas LLM em disco com TTL configurável |
| `sumula_taxonomy.py` | Listas canônicas de súmulas válidas do STJ e STF |

### Quality & Observability
| Módulo | Responsabilidade |
|--------|------------------|
| `quality_gates.py` | Gates formais de qualidade: extração, classificação, cobertura de contexto, fail-closed |
| `quality_streak.py` | Tracking de sequência de aprovação/falha dos quality gates |
| `golden_baseline.py` | Baseline ouro versionado com dataset de referência para regressão |
| `regression_alerts.py` | Alertas automáticos de regressão contra baseline ouro |
| `dead_letter_queue.py` | Fila de falhas não-transientes com snapshot completo para post-mortem |
| `operational_dashboard.py` | Dashboard operacional com métricas agregadas de pipeline |
| `retention_manager.py` | Limpeza automática de artefatos por política de retenção configurável |

### Output & Web
| Módulo | Responsabilidade |
|--------|------------------|
| `output_formatter.py` | Geração de `.md` e `.docx` com formatação jurídica (negrito, seções I/II/III) |
| `state_manager.py` | Serialização/deserialização do estado do pipeline para checkpoints JSON |
| `web_app.py` | API Flask com interface web para upload/processamento; controle de acesso a downloads |

## Key Design Decisions

### External Prompt Architecture
- Instruções do agente vivem fora do código, em `prompts/`
- **Estratégia modular** (`PROMPT_STRATEGY=modular`): `system_base.md` + arquivos por etapa (`dev_etapa1.md`, `dev_etapa2.md`, `dev_etapa3.md`)
- **Estratégia legacy** (`PROMPT_STRATEGY=legacy`): arquivo único `SYSTEM_PROMPT.md` (rollback rápido)
- **Perfil de prompt** (`PROMPT_PROFILE`): `lean` (sem referências longas) ou `full` (injeta `referencias_longas.md` nas etapas 2-3)
- Carregamento via `prompt_loader.py` com cache em memória e hot-reload por timestamp
- Workflow: editar prompt → incrementar versão → testar com caso real → documentar em `PROMPT_CHANGELOG.md`

### Anti-Hallucination Strategy
- Temperatura fixa em 0.0 (saídas determinísticas)
- Validação cruzada entre etapas: Etapa 3 verifica dados contra Etapas 1 & 2
- Transcrições literais verificadas por busca de substring no texto-fonte
- Validação de citações jurídicas: somente súmulas de listas predefinidas (`sumula_taxonomy.py`)
  - **STJ:** 5, 7, 13, 83, 126, 211, 518
  - **STF:** 279, 280, 281, 282, 283, 284, 356, 735
- Política de escalonamento por confiança (`ENABLE_CONFIDENCE_ESCALATION`): escala para revisão humana quando confiança cai abaixo de limiares configuráveis
- Consenso N=2 para campos críticos da Etapa 1 (`ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS`)

### Fail-Closed Quality Gates
- `ENABLE_FAIL_CLOSED=true` bloqueia avanço do pipeline quando validações críticas falham
- Gates: extração de qualidade mínima (`EXTRACTION_MIN_QUALITY_SCORE`), ruído máximo (`EXTRACTION_MAX_NOISE_RATIO`), cobertura de contexto (`CONTEXT_MIN_COVERAGE_RATIO`)
- Classificação com invariantes: exatamente 1 recurso (`REQUIRE_EXACTLY_ONE_RECURSO`), mínimo de acórdãos (`MIN_ACORDAO_COUNT`)
- Revisão manual para classificações ambíguas com limiares de confiança e margem

### Hybrid Model Strategy
- Controlada por feature flag `ENABLE_HYBRID_MODELS`
- `gpt-4.1-mini` para classificação de documentos (93% mais econômico: $0.15/M input, $0.60/M output)
- `gpt-4.1` para análise jurídica (Etapas 1-3) — mantém qualidade ($2.00/M input, $8.00/M output)
- Modelos configuráveis via env vars: `MODEL_CLASSIFICATION`, `MODEL_LEGAL_ANALYSIS`, `MODEL_DRAFT_GENERATION`
- Suporte a múltiplos providers: OpenAI, OpenRouter (deepseek, qwen, claude), Google AI Studio (gemini)

### Token Management & Chunking
- `token_manager.py` estima tokens com `tiktoken` antes de cada chamada
- Chunking inteligente para documentos que excedem 80% do limite de contexto (1M tokens GPT-4.1)
- Budget ratio configurável via `TOKEN_BUDGET_RATIO` (default: 0.7)
- Overlap entre chunks via `CHUNK_OVERLAP_TOKENS` (default: 500)
- Limites granulares por etapa: `MAX_TOKENS_INTERMEDIATE`, `MAX_TOKENS_ETAPA1/2/3`
- Rate limiting por modelo (`ENABLE_RATE_LIMITING`), `MAX_CONTEXT_TOKENS=25000` para respeitar TPM de 30k/min

### OCR Support
- Feature flag `ENABLE_OCR_FALLBACK=false` (ativar com Tesseract instalado)
- Pré-processamento de imagem: deskew, denoise, binarização (flags independentes)
- Trigger automático quando média de caracteres por página cai abaixo de `OCR_TRIGGER_MIN_CHARS_PER_PAGE`
- Idiomas configuráveis: `OCR_LANGUAGES=por+eng`

### State Management & Recovery
- `state_manager.py` serializa estado completo para checkpoints JSON
- Recuperação após interrupções (falhas de API, timeout, abort do usuário)
- Commands CLI: `status` (ver checkpoints), `limpar` (limpar checkpoints), `processar --continuar` (retomar)
- Dead-letter queue (`dead_letter_queue.py`) para falhas não-transientes com snapshot completo

### Retention Policy
- Limpeza automática de artefatos (`ENABLE_RETENTION_POLICY=true`)
- `RETENTION_OUTPUT_DAYS=30`, `RETENTION_CHECKPOINT_DAYS=7`, `RETENTION_WEB_UPLOAD_DAYS=2`, `RETENTION_DEAD_LETTER_DAYS=30`

## Common Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Editar com OPENAI_API_KEY

# Run pipeline
python -m src.main processar recurso.pdf acordao.pdf
python -m src.main processar *.pdf --formato docx --verbose
python -m src.main processar *.pdf --continuar  # Retomar de checkpoint

# Checkpoint management
python -m src.main status
python -m src.main limpar

# Testing
python -m pytest -q                           # Rápido (exclui slow/golden/adversarial)
python -m pytest --cov=src                    # Com cobertura
python -m pytest tests/test_pipeline.py -v    # Módulo específico
python -m pytest -k "test_extraction"         # Filtrar por nome
python -m pytest -m slow                      # Testes de integração (API real)
python -m pytest -m golden                    # Regressão E2E contra dataset ouro
python -m pytest -m adversarial               # Cenários adversariais/fail-closed

# Web API (Flask)
python -m src.web_app                         # Inicia servidor na porta 7860

# Docker
docker compose run --rm app processar <pdf1> <pdf2>
```

## Environment Variables

Definidas em `.env` (copiar de `.env.example`):

### Obrigatórias
| Variável | Descrição | Default |
|----------|-----------|---------|
| `LLM_PROVIDER` | Provider LLM (openai, openrouter, google) | `openai` |
| `OPENAI_API_KEY` | Chave da API OpenAI (se provider=openai) | — (obrigatória) |
| `OPENROUTER_API_KEY` | Chave da API OpenRouter (se provider=openrouter) | — |
| `GOOGLE_API_KEY` | Chave da Google AI Studio (se provider=google) | — |

### LLM & Modelos
| Variável | Descrição | Default |
|----------|-----------|---------|
| `OPENAI_MODEL` | Modelo principal | `gpt-4.1` |
| `TEMPERATURE` | Temperatura de geração | `0.0` |
| `MAX_TOKENS` | Tokens máximos por chamada | `2048` |
| `MAX_TOKENS_INTERMEDIATE` | Tokens para chamadas intermediárias | `700` |
| `MAX_TOKENS_ETAPA1` | Tokens específicos para Etapa 1 | `1400` |
| `MAX_TOKENS_ETAPA2` | Tokens específicos para Etapa 2 | `2200` |
| `MAX_TOKENS_ETAPA3` | Tokens específicos para Etapa 3 | `3200` |
| `LLM_TIMEOUT` | Timeout de requisição (segundos) | `120` |
| `LLM_MAX_RETRIES` | Tentativas para erros transientes | `3` |
| `LOG_LEVEL` | Nível de logging | `INFO` |

### Prompt Configuration
| Variável | Descrição | Default |
|----------|-----------|---------|
| `PROMPT_PROFILE` | Perfil do prompt (lean / full) | `lean` |
| `PROMPT_STRATEGY` | Estratégia de prompt (modular / legacy) | `modular` |
| `ALLOW_MINIMAL_PROMPT_FALLBACK` | Permitir fallback para prompt minimalista | `false` |

### Modelos Híbridos
| Variável | Descrição | Default |
|----------|-----------|---------|
| `MODEL_CLASSIFICATION` | Modelo para classificação | `gpt-4.1-mini` |
| `MODEL_LEGAL_ANALYSIS` | Modelo para análise jurídica | `gpt-4.1` |
| `MODEL_DRAFT_GENERATION` | Modelo para geração de minuta | `gpt-4.1` |

### Feature Flags
| Variável | Descrição | Default |
|----------|-----------|---------|
| `ENABLE_CHUNKING` | Chunking inteligente para documentos grandes | `true` |
| `ENABLE_HYBRID_MODELS` | Roteamento híbrido — reduz custos 60-80% | `true` |
| `ENABLE_RATE_LIMITING` | Gestão proativa de rate limit | `true` |
| `ENABLE_CACHING` | Cache de respostas LLM em disco | `false` |
| `ENABLE_PARALLEL_ETAPA2` | Processamento paralelo na Etapa 2 (~30% mais rápido) | `false` |
| `ENABLE_FAIL_CLOSED` | Bloqueia pipeline em validações críticas | `true` |
| `ENABLE_DEAD_LETTER_QUEUE` | Fila de falhas não-transientes | `true` |
| `ENABLE_CONFIDENCE_ESCALATION` | Escalonamento por confiança | `true` |
| `ENABLE_OCR_FALLBACK` | OCR automático para PDFs escaneados | `false` |
| `ENABLE_EXTRACTION_QUALITY_GATE` | Gate de qualidade da extração | `true` |
| `ENABLE_CONTEXT_COVERAGE_GATE` | Gate de cobertura útil do chunking | `true` |
| `ENABLE_RETENTION_POLICY` | Limpeza automática de artefatos | `true` |
| `ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL` | Controle de acesso para download web | `true` |
| `REQUIRE_EXACTLY_ONE_RECURSO` | Invariante de classificação | `true` |
| `ENABLE_CLASSIFICATION_MANUAL_REVIEW` | Revisão manual para classificações ambíguas | `true` |
| `ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS` | Consenso N=2 para campos críticos Etapa 1 | `false` |

### Confidence Thresholds
| Variável | Descrição | Default |
|----------|-----------|---------|
| `CONFIDENCE_THRESHOLD_GLOBAL` | Limiar de confiança global | `0.75` |
| `CONFIDENCE_THRESHOLD_FIELD` | Limiar para campo crítico (Etapa 1) | `0.75` |
| `CONFIDENCE_THRESHOLD_THEME` | Limiar para tema (Etapa 2) | `0.70` |
| `CLASSIFICATION_MANUAL_REVIEW_CONFIDENCE_THRESHOLD` | Limiar para revisão manual de classificação | `0.65` |
| `CLASSIFICATION_MANUAL_REVIEW_MARGIN_THRESHOLD` | Margem mínima entre classes | `0.15` |

### Token & Cache
| Variável | Descrição | Default |
|----------|-----------|---------|
| `TOKEN_BUDGET_RATIO` | Ratio do limite de contexto | `0.7` |
| `CHUNK_OVERLAP_TOKENS` | Overlap de tokens entre chunks | `500` |
| `MAX_CONTEXT_TOKENS` | Tokens máximos por requisição | `25000` |
| `CACHE_TTL_HOURS` | TTL de cache (horas) | `24` |
| `ETAPA2_PARALLEL_WORKERS` | Workers paralelos na Etapa 2 | `3` |
| `CONTEXT_MIN_COVERAGE_RATIO` | Cobertura mínima aceitável | `0.90` |

### Quality & Extraction
| Variável | Descrição | Default |
|----------|-----------|---------|
| `EXTRACTION_MIN_QUALITY_SCORE` | Score mínimo de qualidade da extração | `0.2` |
| `EXTRACTION_MAX_NOISE_RATIO` | Ruído máximo aceitável | `0.95` |
| `MIN_ACORDAO_COUNT` | Mínimo de acórdãos exigido | `1` |

### OCR
| Variável | Descrição | Default |
|----------|-----------|---------|
| `OCR_LANGUAGES` | Idiomas do Tesseract | `por+eng` |
| `OCR_TRIGGER_MIN_CHARS_PER_PAGE` | Chars mínimos por página (trigger OCR) | `20` |
| `ENABLE_OCR_PREPROCESSING` | Pré-processamento de imagem OCR | `true` |
| `OCR_DESKEW_ENABLED` | Deskew de imagem | `true` |
| `OCR_DENOISE_ENABLED` | Denoise de imagem | `true` |
| `OCR_BINARIZATION_ENABLED` | Binarização de imagem | `true` |
| `OCR_BINARIZATION_THRESHOLD` | Limiar de binarização (0-255) | `160` |
| `OCR_DENOISE_MEDIAN_SIZE` | Kernel de denoise mediana | `3` |

### Retention & Security
| Variável | Descrição | Default |
|----------|-----------|---------|
| `RETENTION_OUTPUT_DAYS` | Retenção de outputs (dias) | `30` |
| `RETENTION_CHECKPOINT_DAYS` | Retenção de checkpoints (dias) | `7` |
| `RETENTION_WEB_UPLOAD_DAYS` | Retenção de uploads web (dias) | `2` |
| `RETENTION_DEAD_LETTER_DAYS` | Retenção de dead letters (dias) | `30` |
| `WEB_DOWNLOAD_TOKEN_TTL_SECONDS` | TTL do token de download (segundos) | `900` |
| `MAX_LOG_MESSAGE_CHARS` | Limite de chars por log sanitizado | `1200` |

## Project Structure

```
agente_assessores/
├── src/                         # Código-fonte principal (26 módulos)
│   ├── main.py                  # CLI entrypoint
│   ├── config.py                # Configuração e env vars
│   ├── pipeline.py              # Orquestrador do pipeline
│   ├── etapa1.py                # Etapa 1 — Recurso
│   ├── etapa2.py                # Etapa 2 — Acórdão
│   ├── etapa3.py                # Etapa 3 — Minuta
│   ├── pdf_processor.py         # Extração de texto de PDFs + OCR fallback
│   ├── classifier.py            # Classificação de documentos
│   ├── llm_client.py            # Cliente LLM multi-provider com retry
│   ├── prompt_loader.py         # Carregamento do prompt (modular/legacy)
│   ├── models.py                # Modelos Pydantic
│   ├── output_formatter.py      # Formatação de saída (.md/.docx)
│   ├── state_manager.py         # Checkpoints de estado
│   ├── token_manager.py         # Gestão de budget de tokens e rate limiting
│   ├── model_router.py          # Roteamento híbrido de modelos
│   ├── cache_manager.py         # Cache de respostas LLM
│   ├── sumula_taxonomy.py       # Listas canônicas de súmulas STJ/STF
│   ├── quality_gates.py         # Gates de qualidade fail-closed
│   ├── quality_streak.py        # Tracking de sequência de aprovação/falha
│   ├── golden_baseline.py       # Baseline ouro para regressão
│   ├── regression_alerts.py     # Alertas de regressão contra baseline
│   ├── dead_letter_queue.py     # Fila de falhas com snapshot
│   ├── operational_dashboard.py # Dashboard operacional
│   ├── retention_manager.py     # Limpeza automática de artefatos
│   └── web_app.py               # API Flask + interface web
├── tests/                       # Suíte de testes (29 arquivos)
│   ├── conftest.py              # Configuração global do pytest
│   ├── fixtures/                # PDFs de teste (válidos, corrompidos, etc.)
│   ├── test_classifier.py
│   ├── test_config.py
│   ├── test_etapa1.py
│   ├── test_etapa2.py
│   ├── test_etapa3.py
│   ├── test_llm_and_prompt.py
│   ├── test_models.py
│   ├── test_pdf_processor.py
│   ├── test_pipeline.py
│   ├── test_pipeline_robust.py
│   ├── test_prompt_loader.py
│   ├── test_token_manager.py
│   ├── test_cache_manager.py
│   ├── test_web_app.py
│   ├── test_golden_baseline.py  # @pytest.mark.golden
│   ├── test_golden_e2e.py       # @pytest.mark.golden
│   ├── test_adversarial_suite.py # @pytest.mark.adversarial
│   ├── test_scanned_pdf_regression.py
│   ├── test_schema_contracts.py
│   ├── test_property_parsers.py
│   ├── test_prompt_regression.py
│   ├── test_quality_gates.py
│   ├── test_quality_streak.py
│   ├── test_regression_alerts.py
│   ├── test_retention_manager.py
│   ├── test_dead_letter_queue.py
│   └── test_operational_dashboard.py
├── prompts/                     # Prompts do agente (fora do código)
│   ├── SYSTEM_PROMPT.md         # Prompt principal legacy
│   ├── PROMPT_CHANGELOG.md      # Histórico de mudanças
│   ├── system_base.md           # Base do sistema (modular)
│   ├── dev_etapa1.md            # Prompt modular — Etapa 1
│   ├── dev_etapa2.md            # Prompt modular — Etapa 2
│   ├── dev_etapa3.md            # Prompt modular — Etapa 3
│   ├── referencias_longas.md    # Referências jurídicas (perfil full)
│   └── originais/               # Versões anteriores do prompt
├── static/css/                  # Assets estáticos (Flask)
├── templates/web/               # Templates HTML (Flask)
├── docs/                        # Documentação técnica (10 docs)
│   ├── README.md                # Índice da documentação
│   ├── visao-geral.md
│   ├── arquitetura.md
│   ├── padroes-desenvolvimento.md
│   ├── estrutura-projeto.md
│   ├── prompt-ia.md
│   ├── glossario.md
│   ├── deploy.md
│   ├── prompt-refinement-sprint7.md
│   └── criterios-aceite-qualidade.md
├── outputs/                     # Minutas geradas e uploads web
├── agents/                      # Instruções para subagentes
├── PRD.md                       # Product Requirements Document
├── CLAUDE.md                    # Este arquivo — guia para Claude Code
├── AGENTS.md                    # Guia para agentes de IA
├── TASKS.md                     # Tracking de sprints/tarefas
├── TASKS_MELHORIAS.md           # Backlog de melhorias
├── CONTRIBUTING.md              # Guia de contribuição
├── requirements.txt             # Dependências Python
├── pytest.ini                   # Config pytest (markers: slow, golden, adversarial)
├── Dockerfile                   # Containerização
├── docker-compose.yml           # Execução local simplificada
├── deploy_hf.sh                 # Script de deploy para Hugging Face Spaces
├── upload_secrets.py            # Upload de secrets para HF
├── .env.example                 # Template de variáveis de ambiente (completo)
└── .gitignore
```

## Coding Conventions

- **Idioma:** Código/variáveis/comentários técnicos em inglês; mensagens ao usuário e documentação em português
- **Type hints:** Obrigatórios em todas as funções
- **Style:** PEP 8 — 4 espaços, `snake_case` funções/vars, `PascalCase` classes, `UPPER_CASE` constantes
- **Logging:** Usar módulo `logging`, nunca `print` (exceto display CLI via `rich`). Logs sanitizados com limite de `MAX_LOG_MESSAGE_CHARS`
- **Error handling:** try/except explícito com mensagens claras para falhas comuns (API key inválida, PDF corrompido, rate limits, fail-closed gates)
- **Commits:** Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`)
- **Prompts:** Alterações em prompts devem ser feitas nos arquivos `.md` em `prompts/`, nunca hardcoded em módulos
- **Modelos/providers LLM:** Mudanças devem respeitar flags e variáveis de ambiente existentes em `config.py`
- **Pipeline order:** Preservar ordem obrigatória: Etapa 1 → Etapa 2 → Etapa 3. Não quebrar contratos de `models.py` sem ajustar testes e consumidores

## Testing Strategy

- **Framework:** pytest + pytest-cov
- **Config:** `pytest.ini` com markers customizados
- **Markers:**
  - `@pytest.mark.slow` — testes de integração que chamam API real ou são demorados
  - `@pytest.mark.golden` — regressão E2E determinística contra dataset ouro versionado
  - `@pytest.mark.adversarial` — cenários adversariais/fail-closed (PDF corrompido, OCR ruim, ambiguidade)
- **Estrutura:** `tests/test_*.py` espelhando módulos em `src/`
- **Fixtures:** PDFs representativos em `tests/fixtures/` (válidos, mínimos, corrompidos, escaneados)
- **Unit tests:** Módulos individuais (PDF extraction, classificação, parsing, token management, quality gates)
- **Integration tests:** Pipeline completo com chamadas reais ao LLM
- **Robust tests:** `test_pipeline_robust.py` — cenários avançados (chunking, modelo híbrido, cache)
- **Golden tests:** `test_golden_baseline.py` + `test_golden_e2e.py` — regressão contra baseline ouro
- **Adversarial tests:** `test_adversarial_suite.py` — PDF corrompido, OCR degradado, classificação ambígua
- **Schema/contract tests:** `test_schema_contracts.py` — verificação de contratos de dados entre módulos
- **Meta:** >80% cobertura para lógica core (pipeline, etapas, parsers)
- **Pre-PR:** `python -m pytest --cov=src`

## Output Structure

Gerado em `outputs/` (ou `--saida` override):

- `minuta_<processo>_<timestamp>.md` (ou `.docx`): Minuta final de admissibilidade
- `auditoria_<processo>_<timestamp>.md`: Relatório de auditoria (tokens, alertas, timestamps)
- `.checkpoints/estado_<id>.json`: Estado serializado do pipeline para recovery
- `web_uploads/`: Uploads temporários via web UI (retenção: 2 dias)

## Prompt Workflow

1. Editar arquivos de prompt em `prompts/` (modular: `system_base.md` + `dev_etapa*.md`; ou legacy: `SYSTEM_PROMPT.md`)
2. Incrementar número de versão e documentar em `prompts/PROMPT_CHANGELOG.md`
3. Testar com pelo menos 1 caso real: `python -m src.main processar <arquivos>`
4. Comparar qualidade da saída com versão anterior
5. Rodar testes: `python -m pytest` (incluindo golden tests para regressão)
6. Documentar alterações no PR

## Common Pitfalls

- **PDF sem OCR:** PDFs escaneados sem texto extraível — habilitar `ENABLE_OCR_FALLBACK=true` com Tesseract instalado. Caso contrário, Quality Gate bloqueia pipeline
- **Limite de contexto:** GPT-4.1 oferece 1M tokens de contexto, mas `MAX_CONTEXT_TOKENS=25000` limita para respeitar TPM. Ajustar conforme tier da API
- **Rate limits (TPM):** GPT-4.1 tem limite de 30k tokens/min. Sistema gerencia via `ENABLE_RATE_LIMITING`, mas pode haver delays em documentos grandes
- **Citações alucinadas:** Validar todas as súmulas/precedentes contra listas em `sumula_taxonomy.py`
- **Retry com backoff:** `llm_client.py` faz retry com backoff exponencial — pode falhar sob carga sustentada
- **Temperatura alta:** Valor >0.1 pode melhorar criatividade mas aumenta risco de alucinação — usar com cautela
- **Cache stale:** Se `ENABLE_CACHING=true`, respostas cached podem estar desatualizadas — ajustar `CACHE_TTL_HOURS`
- **Provider incorreto:** Validar que `LLM_PROVIDER` e a API key correspondente estão configurados
- **Fail-closed silencioso:** Quando `ENABLE_FAIL_CLOSED=true`, pipeline para na falha de quality gate — checar dead-letter queue para diagnóstico
- **Prompt fallback:** Se `ALLOW_MINIMAL_PROMPT_FALLBACK=false` (default), falha na carga do prompt bloqueia o pipeline ao invés de usar fallback minimalista

## Integration Points

- **CLI:** Interface principal via `main.py` — ideal para processamento batch local
- **Web API:** `web_app.py` fornece endpoints Flask para integrações externas:
  - `POST /upload` — recebe PDFs e retorna minuta processada
  - `GET /status` — consulta status de processamento
  - Porta default: 7860 (compatível com Hugging Face Spaces)
  - Integração com n8n via webhook para automação de fluxos
  - Controle de acesso para downloads (`ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL`)
- **Docker:** `Dockerfile` + `docker-compose.yml` para deploy containerizado
- **Hugging Face Spaces:** Deploy via `deploy_hf.sh` + `upload_secrets.py` para gestão de secrets
- **State files:** JSON parseável por ferramentas externas para monitoramento/auditoria
- **Output files:** Formato `.md` facilmente convertível para outros formatos via pandoc

## Development Workflow

1. **Local development:** Usar `.venv` e rodar via CLI para iteração rápida
2. **Prompt refinement:** Editar `prompts/*.md` → testar com caso real → validar contra baseline ouro → commit
3. **Testing:** Rodar suite completa antes de PR: `python -m pytest --cov=src`
4. **Integration testing:** Usar PDFs reais de `tests/fixtures/` ou casos anonimizados
5. **Regression testing:** Rodar `python -m pytest -m golden` para validar contra baseline
6. **Deployment:** Testar em container Docker antes de deploy para evitar problemas de ambiente

## Security & Configuration

- Nunca versionar `.env`, chaves reais ou documentos sensíveis
- Configurar credenciais a partir de `.env.example`
- Tratar `outputs/` como conteúdo gerado potencialmente sensível
- Sanitizar logs e mensagens para não expor dados jurídicos sigilosos
- Downloads web protegidos por tokens descartáveis com TTL configurável
