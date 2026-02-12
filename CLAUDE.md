# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sistema de análise automatizada de recursos jurídicos (Recurso Especial e Extraordinário) do TJPR (Tribunal de Justiça do Paraná). O sistema recebe PDFs fracionados de petições recursais e acórdãos, classifica automaticamente cada documento, executa um pipeline sequencial de 3 etapas via OpenAI API (GPT-4.1) e produz uma minuta formal de decisão de admissibilidade.

**Contexto Jurídico:** O sistema analisa recursos judiciais destinados aos tribunais superiores (STJ/STF), verificando requisitos de admissibilidade conforme legislação processual civil brasileira. O output é uma minuta de decisão monocrática formatada segundo padrões do TJPR.

**Stack:** Python 3.11+, OpenAI API (GPT-4.1 / GPT-4.1-mini), PyMuPDF + pdfplumber, Pydantic, Flask, tiktoken, pytest

**LLM Providers:** OpenAI (default), OpenRouter, Google AI Studio (via env var `LLM_PROVIDER`)

**Documentação completa:** `docs/README.md` (índice) → `docs/visao-geral.md`, `docs/arquitetura.md`, `docs/padroes-desenvolvimento.md`, etc.

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
| `pipeline.py` | Orquestrador: classificação → Etapa 1 → 2 → 3, gestão de estado |
| `etapa1.py` | Análise da petição recursal com parsing estruturado da resposta LLM |
| `etapa2.py` | Análise temática do acórdão com validação de súmulas permitidas |
| `etapa3.py` | Geração da minuta com validação cruzada entre etapas |
| `models.py` | Modelos Pydantic: `DocumentoEntrada`, `ResultadoEtapa1/2/3`, `EstadoPipeline` |

### Ingestion & AI
| Módulo | Responsabilidade |
|--------|------------------|
| `pdf_processor.py` | Extração de texto com PyMuPDF + fallback pdfplumber para PDFs escaneados/corrompidos |
| `classifier.py` | Classificação automática (RECURSO vs ACORDÃO) via heurísticas textuais + LLM fallback |
| `llm_client.py` | Cliente OpenAI reutilizável: retry com backoff exponencial, tracking de tokens, timeout |
| `prompt_loader.py` | Carregamento do `SYSTEM_PROMPT.md` com cache e extração de seções por etapa |

### Robust Architecture (Módulos Avançados)
| Módulo | Responsabilidade |
|--------|------------------|
| `token_manager.py` | Gestão de budget de tokens, estimativa com tiktoken, chunking inteligente de documentos longos |
| `model_router.py` | Roteamento híbrido de modelos (GPT-4o-mini para tarefas simples, GPT-4o para análise crítica) |
| `cache_manager.py` | Cache de respostas LLM em disco com TTL configurável para economia de custos e velocidade |
| `state_manager.py` | Serialização/deserialização do estado do pipeline para checkpoints JSON |

### Output
| Módulo | Responsabilidade |
|--------|------------------|
| `output_formatter.py` | Geração de `.md` e `.docx` com formatação jurídica (negrito, seções I/II/III) |
| `web_app.py` | API Flask para integrações externas (n8n, webhooks) |

## Key Design Decisions

### External Prompt Architecture
- Instruções do agente vivem em `prompts/SYSTEM_PROMPT.md` (fora do código)
- **Justificativa:** Iteração rápida do prompt sem alterar código ou redesploy
- Carregamento via `prompt_loader.py` com cache em memória e hot-reload por timestamp
- Workflow de atualização: editar prompt → incrementar versão → testar com caso real → documentar

### Anti-Hallucination Strategy
- Temperatura fixa em 0.1 (saídas conservadoras)
- Validação cruzada entre etapas: Etapa 3 verifica dados contra Etapas 1 & 2
- Transcrições literais verificadas por busca de substring no texto-fonte
- Validação de citações jurídicas: somente súmulas de listas predefinidas
  - **STJ:** 5, 7, 13, 83, 126, 211, 518
  - **STF:** 279, 280, 281, 282, 283, 284, 356, 735

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
- Overlap entre chunks via `CHUNK_OVERLAP_TOKENS` (default: 500) para manter contexto
- Rate limiting por modelo configurável em `RATE_LIMIT_TPM` (ex: GPT-4.1 = 30k TPM, GPT-4.1-mini = 200k TPM)
- `MAX_CONTEXT_TOKENS` limita requisições a 25k tokens para respeitar TPM de 30k/min

### State Management & Recovery
- `state_manager.py` serializa estado completo para checkpoints JSON
- Recuperação após interrupções (falhas de API, timeout, abort do usuário)
- Commands CLI: `status` (ver checkpoints), `limpar` (limpar checkpoints), `processar --continuar` (retomar)
- Estado inclui: metadata de documentos, resultados de todas as etapas, tokens consumidos, timestamps

### Rate Limiting Strategy
- Feature flag `ENABLE_RATE_LIMITING` ativa gestão proativa de TPM (tokens per minute)
- Configuração por modelo em `RATE_LIMIT_TPM` no `config.py`:
  - GPT-4.1: 30k TPM
  - GPT-4.1-mini: 200k TPM
  - OpenRouter models: 40k-2M TPM (conforme provider)
  - Google Gemini: 1M-2M TPM
- Sistema aguarda automaticamente quando próximo do limite para evitar erros 429
- `MAX_CONTEXT_TOKENS=25000` garante que requisições individuais não excedam TPM de 30k/min

### Multi-Provider LLM Support
- Sistema suporta 3 providers via env var `LLM_PROVIDER`:
  - **openai** (default): GPT-4.1, GPT-4.1-mini, GPT-4o
  - **openrouter**: DeepSeek R1/Chat, Qwen 2.5, Claude 3.5, Gemini (via proxy)
  - **google**: Google AI Studio direct (Gemini 2.0/2.5 Flash)
- Cada provider requer sua API key correspondente (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`)
- `llm_client.py` abstrai diferenças entre providers com interface unificada
- Modelos configuráveis por etapa: permite usar DeepSeek para classificação + GPT-4.1 para análise

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

# Testing
python -m pytest -q                           # Rápido
python -m pytest --cov=src                    # Com cobertura
python -m pytest tests/test_pipeline.py -v    # Módulo específico
python -m pytest -k "test_extraction"         # Filtrar por nome

# Checkpoint management
python -m src.main status
python -m src.main limpar

# Web API (Flask)
python -m src.web_app                         # Inicia servidor na porta 7860
curl -X POST http://localhost:7860/upload \  # Exemplo de upload
  -F "recurso=@recurso.pdf" \
  -F "acordao=@acordao.pdf"
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
| `LLM_TIMEOUT` | Timeout de requisição (segundos) | `120` |
| `LLM_MAX_RETRIES` | Tentativas para erros transientes | `3` |
| `LOG_LEVEL` | Nível de logging | `INFO` |
| `OPENROUTER_BASE_URL` | URL base do OpenRouter | `https://openrouter.ai/api/v1` |

### Feature Flags
| Variável | Descrição | Default |
|----------|-----------|---------|
| `ENABLE_CHUNKING` | Chunking inteligente para documentos longos | `true` |
| `ENABLE_HYBRID_MODELS` | Roteamento híbrido (mini + 4o) — reduz custos 60-80% | `true` |
| `ENABLE_RATE_LIMITING` | Gestão proativa de rate limit | `true` |
| `ENABLE_CACHING` | Cache de respostas LLM em disco | `false` |
| `ENABLE_PARALLEL_ETAPA2` | Processamento paralelo na Etapa 2 (~30% mais rápido) | `false` |

### Configuração de Modelos Híbridos
| Variável | Descrição | Default |
|----------|-----------|---------|
| `MODEL_CLASSIFICATION` | Modelo para classificação | `gpt-4.1-mini` |
| `MODEL_LEGAL_ANALYSIS` | Modelo para análise jurídica | `gpt-4.1` |
| `MODEL_DRAFT_GENERATION` | Modelo para geração de minuta | `gpt-4.1` |

### Token & Cache
| Variável | Descrição | Default |
|----------|-----------|---------|
| `TOKEN_BUDGET_RATIO` | Ratio do limite de contexto a usar como budget | `0.7` |
| `CHUNK_OVERLAP_TOKENS` | Overlap de tokens entre chunks | `500` |
| `MAX_CONTEXT_TOKENS` | Tokens máximos de contexto por requisição (respeita TPM) | `25000` |
| `CACHE_TTL_HOURS` | TTL do cache de respostas (horas) | `24` |
| `ETAPA2_PARALLEL_WORKERS` | Workers paralelos na Etapa 2 | `3` |

## Project Structure

```
agente_assessores/
├── src/                         # Código-fonte principal
│   ├── main.py                  # CLI entrypoint
│   ├── config.py                # Configuração e env vars
│   ├── pipeline.py              # Orquestrador do pipeline
│   ├── etapa1.py                # Etapa 1 — Recurso
│   ├── etapa2.py                # Etapa 2 — Acórdão
│   ├── etapa3.py                # Etapa 3 — Minuta
│   ├── pdf_processor.py         # Extração de texto de PDFs
│   ├── classifier.py            # Classificação de documentos
│   ├── llm_client.py            # Cliente LLM multi-provider com retry
│   ├── prompt_loader.py         # Carregamento do prompt externo
│   ├── models.py                # Modelos Pydantic
│   ├── output_formatter.py      # Formatação de saída (.md/.docx)
│   ├── state_manager.py         # Checkpoints de estado
│   ├── token_manager.py         # Gestão de budget de tokens
│   ├── model_router.py          # Roteamento híbrido de modelos
│   ├── cache_manager.py         # Cache de respostas LLM
│   └── web_app.py               # API Flask
├── tests/                       # Testes
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
│   └── test_token_manager.py
├── prompts/
│   ├── SYSTEM_PROMPT.md         # Prompt principal (separado do código)
│   └── originais/               # Versões anteriores do prompt
├── static/                      # Assets estáticos (CSS, JS) para Flask
│   └── css/
├── templates/                   # Templates HTML (Flask)
│   └── web/
├── docs/                        # Documentação técnica
│   ├── README.md                # Índice da documentação
│   ├── visao-geral.md           # Visão geral do projeto
│   ├── arquitetura.md           # Arquitetura técnica
│   ├── padroes-desenvolvimento.md
│   ├── estrutura-projeto.md
│   ├── prompt-ia.md
│   ├── glossario.md
│   ├── deploy.md
│   └── prompt-refinement-sprint7.md
├── outputs/                     # Minutas geradas
│   └── web_uploads/             # Uploads temporários via web UI
├── htmlcov/                     # Relatórios de cobertura de testes
├── PRD.md                       # Product Requirements Document
├── CLAUDE.md                    # Guia para Claude Code
├── AGENTS.md                    # Guia para agentes de IA
├── TASKS.md                     # Tracking de sprints/tarefas
├── requirements.txt             # Dependências Python
├── Dockerfile                   # Containerização
├── docker-compose.yml           # Execução local simplificada
├── .env.example                 # Template de variáveis de ambiente
└── .gitignore
```

## Coding Conventions

- **Idioma:** Código/variáveis/comentários em inglês; mensagens ao usuário em português
- **Type hints:** Obrigatórios em todas as funções
- **Style:** PEP 8 — 4 espaços, `snake_case` funções/vars, `PascalCase` classes, `UPPER_CASE` constantes
- **Logging:** Usar módulo `logging`, nunca `print` (exceto display CLI via `rich`)
- **Error handling:** try/except explícito com mensagens claras para falhas comuns (API key inválida, PDF corrompido, rate limits)
- **Commits:** Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`)

## Testing Strategy

- **Framework:** pytest + pytest-cov
- **Estrutura:** `tests/test_*.py` espelhando módulos em `src/`
- **Fixtures:** PDFs representativos em `tests/fixtures/` (válidos, mínimos, corrompidos, escaneados)
- **Unit tests:** Módulos individuais (PDF extraction, classificação, parsing, token management)
- **Integration tests:** Pipeline completo com chamadas reais ao LLM (marcar com `@pytest.mark.slow`)
- **Robust tests:** `test_pipeline_robust.py` testa cenários avançados (chunking, modelo híbrido, cache)
- **Meta:** >80% cobertura para lógica core (pipeline, etapas, parsers)
- **Pre-PR:** `python -m pytest --cov=src`

## Output Structure

Gerado em `outputs/` (ou `--saida` override):

- `minuta_<processo>_<timestamp>.md` (ou `.docx`): Minuta final de admissibilidade
- `auditoria_<processo>_<timestamp>.md`: Relatório de auditoria (tokens, alertas, timestamps)
- `.checkpoints/estado_<id>.json`: Estado serializado do pipeline para recovery

## Prompt Workflow

1. Editar `prompts/SYSTEM_PROMPT.md` com alterações de instrução
2. Incrementar número de versão no header do prompt
3. Testar com pelo menos 1 caso real: `python -m src.main processar <arquivos>`
4. Comparar qualidade da saída com versão anterior
5. Rodar testes: `python -m pytest`
6. Documentar alterações no PR

## Common Pitfalls

- **PDF sem OCR:** PDFs escaneados sem texto extraível — pdfplumber fallback pode não resolver. Futuro: integrar Tesseract OCR
- **Limite de contexto:** GPT-4.1 oferece 1M tokens de contexto, mas casos muito grandes ainda necessitam chunking — controlado por `token_manager.py` e flag `ENABLE_CHUNKING`
- **Rate limits (TPM):** GPT-4.1 tem limite de 30k tokens/min. Sistema gerencia automaticamente via `ENABLE_RATE_LIMITING`, mas pode haver delays em documentos grandes. `MAX_CONTEXT_TOKENS=25000` previne exceder TPM em requisições únicas
- **Citações alucinadas:** Validar todas as súmulas/precedentes contra listas permitidas em `etapa2.py`
- **Retry com backoff:** `llm_client.py` faz retry com backoff exponencial — pode falhar sob carga sustentada ou problemas de rede
- **Temperatura alta:** Acima de 0.1 pode melhorar criatividade mas aumenta risco de alucinação — testar cuidadosamente
- **Cache stale:** Se `ENABLE_CACHING=true`, respostas cached podem estar desatualizadas — ajustar `CACHE_TTL_HOURS` conforme necessidade
- **Provider incorreto:** Validar que `LLM_PROVIDER` está configurado e a API key correspondente está presente (OpenAI, OpenRouter, ou Google)

## Integration Points

- **CLI:** Interface principal via `main.py` — ideal para processamento batch local
- **Web API:** `web_app.py` fornece endpoints Flask para integrações externas:
  - `POST /upload` — recebe PDFs e retorna minuta processada
  - `GET /status` — consulta status de processamento
  - Porta default: 7860 (Hugging Face Spaces compatible)
  - Integração com n8n via webhook para automação de fluxos
- **Docker:** `Dockerfile` + `docker-compose.yml` para deploy containerizado
- **Hugging Face Spaces:** Deploy via git remote `space` configurado no repositório
  - Usa Docker SDK com porta 7860
  - Requer Git LFS para arquivos >10MB (PDFs de manual)
- **State files:** JSON parseável por ferramentas externas para monitoramento/auditoria
- **Output files:** Formato `.md` facilmente convertível para outros formatos via pandoc

## Development Workflow

1. **Local development:** Usar `.venv` e rodar via CLI para iteração rápida
2. **Prompt refinement:** Editar `prompts/SYSTEM_PROMPT.md` → testar com caso real → validar qualidade → commit
3. **Testing:** Rodar suite completa antes de PR: `python -m pytest --cov=src`
4. **Integration testing:** Usar PDFs reais de `tests/fixtures/` ou casos anonimizados
5. **Deployment:** Testar em container Docker antes de deploy para evitar problemas de ambiente
