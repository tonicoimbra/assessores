# TASKS_MELHORIAS_02 — Eficiência, Segurança e Precisão Jurídica

> **Contexto**: Segunda rodada de melhorias gerada após análise técnica criteriosa (especialista sênior em IA jurídica).
> Todos os itens do `TASKS_MELHORIAS.md` foram marcados como `[x]`. Este documento cobre as **lacunas residuais** identificadas.
>
> **Score atual estimado**: 7.7/10 → **Meta**: 9.5/10

---

## Status de Execução

- [x] **SEC-005** — Criptografar conteúdo da Dead Letter Queue (Concluído)
- [x] **SEC-006** — Autenticação e autorização na web_app (Concluído)
- [x] **SEC-007** — TTL e política de expiração do cache de conteúdo processual (Concluído)
- [x] **SEC-008** — Sanitização de dados sensíveis em todos os níveis de log (Concluído)
- [x] **Sprint 1 — Segurança** (SEC-005 → SEC-008 concluído)
- [x] **PDF-010** — Paralelizar OCR por página (Concluído)
- [x] **PDF-011** — OCR seletivo por página (Concluído)
- [x] **Sprint 2 — Performance OCR** (PDF-010 → PDF-011 concluído)
- [x] **CLS-006** — Adicionar patterns para Agravo e demais espécies recursais (Concluído)
- [x] **CLS-007** — Busca de patterns em múltiplas janelas do documento (Concluído)
- [x] **CLS-008** — Few-shot no prompt do classificador LLM (Concluído)
- [x] **E3-006** — Normalização de aspas na validação de transcrições (Concluído)
- [x] **E3-007** — Normalização de espaço na extração de decisão (Concluído)
- [x] **E3-008** — Estratégia de redução de contexto no retry da Etapa 3 (Concluído)
- [x] **Sprint 3 — Qualidade Jurídica** (CLS-006 → CLS-008; E3-006 → E3-008 concluído)
- [x] **MIN-001** — Embedding semântico para seleção de minutas (Concluído)
- [x] **MIN-002** — Truncamento inteligente da minuta de referência por seção (Concluído)
- [x] **Sprint 4 — Seleção Inteligente de Minutas** (MIN-001 → MIN-002 concluído)
- [x] **CONF-001** — Tornar pesos de confiança configuráveis via `.env` (Concluído)
- [x] **CONF-002** — Pricing de LLM configurável e atualizado (Concluído)
- [x] **CONF-003** — Teto de tokens configurável no LLM client (Concluído)
- [x] **Sprint 5 — Configurabilidade** (CONF-001 → CONF-003 concluído)
- [x] **LLM-007** — Circuit breaker para falhas consecutivas da API (Concluído)
- [x] **LLM-008** — Idempotência persistente entre reinicializações (Concluído)
- [x] **PDF-012** — Suporte a documentos DOCX (Concluído)
- [x] **OBS-005** — Métricas de qualidade de minuta por tipo de caso (Concluído)
- [x] **OBS-006** — Alerta de degradação de qualidade por tipo de Recurso (Concluído)
- [x] **Sprint 6 — Robustez e Escala** (LLM-007 → LLM-008 → PDF-012 → OBS-005 → OBS-006 concluído)

---

## 🔴 Fase A — Crítico de Produção (P0)

> Riscos que **bloqueiam uso seguro em ambiente judicial real**. Implementar antes de qualquer deploy.

---

### A1. Segurança e LGPD

#### `SEC-005` — Criptografar conteúdo da Dead Letter Queue

**Arquivo**: `src/dead_letter_queue.py`
**Problema**: Textos completos de petições e acórdãos são persistidos em JSON em texto plano no disco. Dados processuais são sensíveis conforme LGPD e política interna do TJPR.

**Implementação**:
- [x] Adicionar dependência `cryptography` ao `requirements.txt`
- [x] Criar utilitário `src/crypto_utils.py` com funções `encrypt_json(data, key)` e `decrypt_json(blob, key)`  usando `Fernet` (AES-128-CBC + HMAC-SHA256)
- [x] Adicionar variável `DLQ_ENCRYPTION_KEY` ao `.env` e `.env.example`
- [x] Modificar `salvar_dead_letter()` para criptografar payload antes de salvar
- [x] Adicionar função `ler_dead_letter(path)` que descriptografa para inspeção
- [x] Atualizar testes em `tests/` para cobrir round-trip encrypt/decrypt
- [x] Documentar em `docs/` como rotar a chave com re-encriptação dos arquivos existentes

---

#### `SEC-006` — Autenticação e autorização na web_app

**Arquivo**: `src/web_app.py`
**Problema**: A interface web não possui camada de autenticação — qualquer pessoa com acesso à rede pode submeter processos e baixar minutas.

**Implementação**:
- [x] Avaliar estratégia: Basic Auth (simples) vs. token Bearer via `python-jwt` vs. integração LDAP do TJPR
- [x] Implementar middleware de autenticação (preferencialmente token Bearer)
- [x] Adicionar variáveis `WEB_AUTH_ENABLED`, `WEB_AUTH_TOKEN` ao `.env`
- [x] Proteger rotas de upload, processamento e download de minutas
- [x] Adicionar header de segurança: `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`
- [x] Adicionar rate limiting por IP na web_app (`UPLOAD_RATE_LIMIT_PER_MINUTE`)
- [x] Logar tentativas de acesso não autorizado com IP e timestamp

---

#### `SEC-007` — TTL e política de expiração do cache de conteúdo processual

**Arquivo**: `src/cache_manager.py`
**Problema**: Textos de acórdãos ficam em cache indefinidamente sem expiração, violando potencialmente políticas de retenção de dados.

**Implementação**:
- [x] Adicionar `CACHE_TTL_SECONDS` ao `.env` (default: `86400` = 24h)
- [x] Implementar verificação de TTL no método `get()` do `cache_manager`
- [x] Adicionar job de limpeza automática `src/cache_manager.py::purge_expired()`
- [x] Invocar `purge_expired()` no início de cada execução de pipeline (opcional, via flag `CACHE_PURGE_ON_START`)
- [x] Documentar política de retenção em `docs/`

---

#### `SEC-008` — Sanitização de dados sensíveis em todos os níveis de log

**Arquivo**: `src/pipeline.py`, `src/config.py` (`SensitiveDataFilter`)
**Problema**: O `SensitiveDataFilter` só filtra logs de nível `ERROR`. Logs `INFO` contêm nomes de partes, números de processo e trechos de petições.

**Implementação**:
- [x] Aplicar `SensitiveDataFilter` em **todos** os handlers (não apenas `FileHandler`)
- [x] Expandir filtro para mascarar: CPF, CNPJ, nomes de partes (detectados por padrão), números de processo
- [x] Adicionar modo `LOG_SANITIZE_LEVEL=full|partial|off` no `.env`
- [x] Criar teste unitário que verifica ausência de dados pessoais nos logs
- [x] Aplicar filtro ao handler de console também (`StreamHandler`)

---

### A2. Performance Crítica

#### `PDF-010` — Paralelizar OCR por página

**Arquivo**: `src/pdf_processor.py`, função `_extrair_com_ocr()`
**Problema**: O OCR processa páginas sequencialmente. Um acórdão de 80 páginas escaneadas leva 3–8 minutos — inaceitável para produção.

**Implementação**:
- [x] Adicionar variável `OCR_MAX_WORKERS` ao `.env` e `config.py` (default: `4`)
- [x] Refatorar `_extrair_com_ocr()` para usar `concurrent.futures.ThreadPoolExecutor`
- [x] Garantir thread-safety: cada thread opera em sua própria instância de `fitz.Document` (abrir por thread)
- [x] Reorganizar resultados no final por índice de página (preservar ordem)
- [x] Adicionar timeout por página: se OCR de uma página travar, usar string vazia com log de aviso
- [x] Adicionar métrica `ocr_processing_time_ms` no `ExtractionResult`
- [x] Benchmark: medir ganho de tempo com 4 e 8 workers em PDF de teste de 50 páginas

---

#### `PDF-011` — OCR seletivo por página (modo híbrido)

**Arquivo**: `src/pdf_processor.py`, função `extrair_texto()`
**Problema**: Documentos híbridos (parte texto nativo, parte escaneado) ativam OCR para o documento inteiro, desperdiçando tempo nas páginas que já têm texto.

**Implementação**:
- [x] Adicionar função `_paginas_que_precisam_ocr(resultado: ExtractionResult) -> list[int]`
  - Critério: páginas com `quality_score_by_page[i] < OCR_TRIGGER_MIN_CHARS_PER_PAGE` OU `noise_ratio_by_page[i] > 0.8`
- [x] Modificar `_extrair_com_ocr()` para aceitar parâmetro `pages_only: list[int] | None`
- [x] Na função principal `extrair_texto()`, chamar OCR seletivo antes do OCR completo
- [x] Mesclar resultado: páginas nativas do PyMuPDF + páginas OCR onde necessário
- [x] Registrar no `ExtractionResult.pages_with_ocr` apenas as páginas efetivamente OCR-izadas

---

## 🟡 Fase B — Qualidade de Output Jurídico (P1)

> Melhoram significativamente a precisão das minutas e da classificação sem afetar segurança imediata.

---

### B1. Classificação de Documentos

#### `CLS-006` — Adicionar patterns para Agravo e demais espécies recursais

**Arquivo**: `src/classifier.py`
**Problema**: Agravos (em Recurso Especial, Regimental, Interno) são comuns no TJPR mas não estão cobertos pelos patterns de classificação, podendo ser misclassificados como ACORDAO.

**Implementação**:
- [x] Adicionar ao `RECURSO_PATTERNS`:
  ```python
  r"Agravo\s+(?:em\s+Recurso\s+Especial|Regimental|Interno)",
  r"AREsp\b",
  r"Embargos?\s+de\s+Decla(?:ração|ração)",
  r"recurso\s+de\s+revista",
  ```
- [x] Adicionar ao `CHEAP_VERIFIER_RECURSO_PATTERNS`:
  ```python
  r"agravo\s+(?:em\s+recurso|regimental|interno)",
  r"aresp\b",
  ```
- [x] Criar fixture em `tests/fixtures/` com exemplos de cada tipo recursal
- [x] Adicionar testes de classificação para cada novo tipo
- [x] Verificar se `_parse_especie_recurso()` em `etapa1.py` também cobre os novos tipos

---

#### `CLS-007` — Busca de patterns em múltiplas janelas do documento

**Arquivo**: `src/classifier.py`, funções `_calcular_score_heuristico()` e `_match_patterns_with_evidence()`
**Problema**: A busca é limitada aos primeiros 5000 caracteres. Documentos com capa/préambulo extensos podem ter o conteúdo relevante além desse ponto.

**Implementação**:
- [x] Refatorar para busca em 3 janelas: `texto[:5000]`, `texto[len//2-2500:len//2+2500]`, `texto[-5000:]`
- [x] Consolidar matches de todas as janelas (deduplicar por padrão)
- [x] Score = melhor resultado entre as janelas (não soma — evitar viés por repetição)
- [x] Adicionar testes com documentos que têm capa longa (> 5000 chars antes do corpo)

---

#### `CLS-008` — Few-shot no prompt do classificador LLM

**Arquivo**: `src/classifier.py`, constante `CLASSIFICATION_PROMPT`
**Problema**: O prompt do LLM classifier é simplista e sem exemplos. Casos ambíguos (Embargos, Agravo) são mal classificados.

**Implementação**:
- [x] Adicionar 2 exemplos RECURSO e 2 exemplos ACORDAO no prompt (casos reais anonimizados)
- [x] Adicionar 1 exemplo de cada caso limítrofe (Embargos, Agravo Regimental)
- [x] Versionar o prompt atualizado no `PROMPT_CHANGELOG.md`
- [x] Criar teste de regressão: classificar 10 documentos de referência e verificar ≥ 90% acerto

---

### B2. Seleção de Minutas de Referência

#### `MIN-001` — Embedding semântico para seleção de minutas

**Arquivo**: `src/minuta_selector.py`
**Problema**: O score linear atual (tipo_recurso=10, decisão=5, súmula=3, matéria=1) é ingênuo e pode selecionar minutas inadequadas quando os metadados não batem perfeitamente.

**Implementação**:
- [x] Adicionar dependência `sentence-transformers` (modelo leve: `paraphrase-multilingual-MiniLM-L12-v2`) ao `requirements.txt`
- [x] Criar script `scripts/indexar_minutas_embeddings.py` que:
  - Lê cada `minutas_referencia/textos/*.txt`
  - Gera embedding do texto completo
  - Salva em `minutas_referencia/embeddings.pkl` (pickle de dict: `id → vector`)
- [x] Modificar `selecionar_minuta_referencia()`:
  - Se `embeddings.pkl` existir, usar similaridade de cosseno como critério primário
  - Score composto: `0.7 * cosine_similarity + 0.3 * score_linear_atual`
  - Fallback para score linear caso embeddings não estejam disponíveis
- [x] Adicionar `recarregar_embeddings()` análogo ao `recarregar_indice()`
- [x] Documentar em `docs/` como regenerar os embeddings após importar novas minutas

---

#### `MIN-002` — Truncamento inteligente da minuta de referência por seção

**Arquivo**: `src/minuta_selector.py`, função `_truncar_texto()`
**Problema**: Truncamento por caracteres pode cortar exatamente a Seção III (Decisão), que é a parte mais importante para o LLM aprender o estilo.

**Implementação**:
- [x] Implementar `_truncar_por_secoes(texto, max_chars)`:
  - Identificar seções I, II, III por regex
  - Reduzir proporcionalmente seção II (mais verbosa) antes de I e III
  - Preservar seção III completa sempre que possível
- [x] Substituir uso de `_truncar_texto()` por `_truncar_por_secoes()` em `selecionar_minuta_referencia()`
- [x] Criar testes com minutas longas (> 6000 chars) verificando que Seção III é preservada

---

### B3. Validação e Anti-Alucinação

#### `E3-006` — Normalização de aspas na validação de transcrições

**Arquivo**: `src/etapa3.py`, função `_validar_transcricoes()`
**Problema**: A validação usa apenas aspas duplas ASCII `"`. Documentos jurídicos brasileiros usam `"`, `"`, `'`, `»`, introduzidas por processadores de texto.

**Implementação**:
- [x] Criar função `_normalizar_aspas(texto: str) -> str` que unifica todas as variantes para `"`
- [x] Aplicar antes de `re.findall(r'"([^"]{30,})"', minuta)` e antes da busca em `texto_acordao`
- [x] Adicionar testes com cada variante de aspas

---

#### `E3-007` — Normalização de espaço na extração de decisão

**Arquivo**: `src/etapa3.py`, função `_extrair_decisao()`
**Problema**: O lookbehind `(?<!IN)ADMITO` pode falhar se houver quebra de linha ou espaço extra entre "IN" e "ADMITO" (ex: formatação PDF).

**Implementação**:
- [x] Antes de aplicar regex de decisão, normalizar: `re.sub(r'\s+', ' ', minuta)`
- [x] Adicionar variantes: `"NÃO ADMITO"`, `"NÃO SE CONHECE"`, `"NÃO CONHECE"` como sinônimo de INADMITIDO
- [x] Adicionar teste unitário com texto contendo quebra de linha entre "IN" e "ADMITO"

---

#### `E3-008` — Estratégia de redução de contexto no retry da Etapa 3

**Arquivo**: `src/etapa3.py`, function `executar_etapa3()`
**Problema**: Nas 2 tentativas estruturadas, apenas o prompt é reforçado. Se o modelo falhar por contexto longo (> limite), a tentativa 2 tem o mesmo problema.

**Implementação**:
- [x] Na tentativa 2, reduzir `texto_acordao_ctx` em 25% antes de montar o user_message
- [x] Adicionar instrução de concisão: `"Seja conciso. Minuta máxima de 800 palavras."`
- [x] Adicionar tentativa 3 (se ENABLE_FAIL_CLOSED=False): usar somente Etapas 1 e 2 sem texto do acórdão
- [x] Registrar qual tentativa foi bem-sucedida no metadata do pipeline

---

### B4. Configurabilidade e Calibração

#### `CONF-001` — Tornar pesos de confiança configuráveis via `.env` (Concluído)

**Arquivo**: `src/pipeline.py`, constante `pesos = {"etapa1": 0.35, ...}`
**Problema**: Pesos hardcoded não foram calibrados empiricamente. Após acumular casos reais, podem precisar de ajuste.

**Implementação**:
- [x] Adicionar ao `config.py`:
  ```python
  CONFIDENCE_WEIGHT_ETAPA1 = float(os.getenv("CONFIDENCE_WEIGHT_ETAPA1", "0.35"))
  CONFIDENCE_WEIGHT_ETAPA2 = float(os.getenv("CONFIDENCE_WEIGHT_ETAPA2", "0.35"))
  CONFIDENCE_WEIGHT_ETAPA3 = float(os.getenv("CONFIDENCE_WEIGHT_ETAPA3", "0.30"))
  ```
- [x] Validar na inicialização: soma dos 3 pesos deve ser `1.0` (± 0.001)
- [x] Adicionar ao `.env.example` com comentário explicando como calibrar
- [x] Documentar procedimento de calibração em `docs/calibracao_confianca.md`

---

#### `CONF-002` — Pricing de LLM configurável e atualizado (Concluído)

**Arquivo**: `src/pipeline.py`, constante `PRICING`
**Problema**: Preços hardcoded de 2024 ficam desatualizados. OpenRouter muda preços frequentemente.

**Implementação**:
- [x] Criar `pricing.json` na raiz do projeto com estrutura:
  ```json
  {
    "version": "2025-03",
    "models": {
      "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
      ...
    }
  }
  ```
- [x] Modificar `_estimar_custo()` para carregar de `pricing.json` (lazy, com cache em memória)
- [x] Fallback para constante hardcoded se `pricing.json` não existir
- [x] Criar script `scripts/atualizar_pricing.py` que consulta `https://openrouter.ai/api/v1/models` e atualiza o arquivo
- [x] Adicionar instrução em `README_DEPLOY.md` para atualizar pricing mensalmente

---

#### `CONF-003` — Teto de tokens configurável no LLM client (Concluído)

**Arquivo**: `src/llm_client.py`, função `_chamar_llm_raw()`
**Problema**: O teto de 8192 tokens no retry por truncamento é hardcoded e pode ser insuficiente para minutas de processos complexos.

**Implementação**:
- [x] Adicionar `MAX_TOKENS_CEILING` ao `config.py` e `.env` (default: `12000`)
- [x] Substituir `min(tokens + ..., 8192)` por `min(tokens + ..., MAX_TOKENS_CEILING)`
- [x] Adicionar validação: `MAX_TOKENS_CEILING >= MAX_TOKENS` (senão logar aviso)

---

## 🟢 Fase C — Robustez e Evolução (P2)

> Melhorias de médio prazo que aumentam resiliência e capacidade de escala.

---

### C1. Resiliência do LLM Client

#### `LLM-007` — Circuit breaker para falhas consecutivas da API (Concluído)

**Arquivo**: `src/llm_client.py`
**Problema**: Se a API estiver indisponível por 10 minutos, todas as chamadas falham sequencialmente após esgotar retries, desperdiçando tempo e recursos.

**Implementação**:
- [x] Implementar classe `CircuitBreaker` em `src/llm_client.py`:
  - Estados: `CLOSED` (normal), `OPEN` (bloqueado), `HALF_OPEN` (testando)
  - Threshold: `CIRCUIT_BREAKER_FAILURE_THRESHOLD=5` falhas consecutivas → abre circuito
  - Tempo de espera: `CIRCUIT_BREAKER_RESET_TIMEOUT=60` segundos
- [x] Integrar no `_chamar_llm_raw()`: verificar estado antes de chamar API
- [x] Registrar métricas: `circuit_opens`, `circuit_half_opens` no log estruturado
- [x] Adicionar ao `.env.example` com comentário sobre uso

---

#### `LLM-008` — Idempotência persistente entre reinicializações (Concluído)

**Arquivo**: `src/llm_client.py`, `_IDEMPOTENCY_CACHE`
**Problema**: O cache de idempotência está em memória e desaparece ao reiniciar o processo, permitindo re-execuções duplicadas em batch.

**Implementação**:
- [x] Adicionar `IDEMPOTENCY_BACKEND=memory|sqlite` ao `.env` (default: `memory`)
- [x] Para backend `sqlite`: criar tabela `idempotency_cache(request_id, fingerprint, response_json, created_at)`
- [x] Implementar adapter com interface compatível à atual
- [x] TTL automático: registros com `created_at` > 24h são ignorados
- [x] Usar `src/cache_manager.py` existente como backend alternativo (sem SQLite extra)

---

### C2. Cobertura de Tipos de Documento

#### `PDF-012` — Suporte a documentos DOCX (Concluído)

**Arquivo**: `src/pdf_processor.py` (novo: `src/document_extractor.py`)
**Problema**: Petições eletrônicas podem chegar como DOCX. O sistema rejeita qualquer arquivo não-PDF.

**Implementação**:
- [x] Criar `src/document_extractor.py` com interface `extract_text(filepath: str) -> ExtractionResult`
- [x] Implementar adapter para DOCX via `python-docx`
- [x] Manter `pdf_processor.py` como adapter para PDF
- [x] Registrar automaticamente: `.pdf` → `pdf_processor`, `.docx` → `docx_extractor`
- [x] Atualizar `extrair_multiplos_pdfs()` → `extrair_multiplos_documentos()` aceitando ambos
- [x] Adicionar `python-docx` ao `requirements.txt`
- [x] Testes com DOCX simples e com DOCX gerado pelo TJPR

---

### C3. Observabilidade Avançada

#### `OBS-005` — Métricas de qualidade de minuta por tipo de caso (Concluído)

**Arquivo**: `src/operational_dashboard.py`
**Implementação**:
- [x] Adicionar ao dashboard: distribuição de `decisao` (ADMITIDO/INADMITIDO/INCONCLUSIVO) por semana
- [x] Adicionar: taxa de minutas com alertas de validação (seções ausentes, súmulas não encontradas)
- [x] Adicionar: top-5 tipos de alerta mais frequentes
- [x] Exportar como CSV ou JSON para análise externa
- [x] Adicionar endpoint `/metrics` na `web_app.py` retornando JSON com métricas do último período

---

#### `OBS-006` — Alerta de degradação de qualidade por tipo de Recurso (Concluído)

**Arquivo**: `src/regression_alerts.py`
**Problema**: O sistema de alertas existente monitora regressões mas não segmenta por tipo de recurso (RE vs REsp), que podem ter padrões de qualidade diferentes.

**Implementação**:
- [x] Estender `regression_alerts.py` para rastrear métricas separadas por `especie_recurso`
- [x] Alertar quando taxa de INCONCLUSIVO para um tipo específico > threshold configurável
- [x] Integrar ao relatório de auditoria existente

---

## 📋 Resumo por Prioridade

| ID | Título | Prioridade | Arquivos Afetados | Esforço |
|---|---|---|---|---|
| `SEC-005` | Criptografar DLQ | 🔴 P0 | `dead_letter_queue.py`, novo `crypto_utils.py` | Médio |
| `SEC-006` | Autenticação web_app | 🔴 P0 | `web_app.py` | Médio |
| `SEC-007` | TTL cache processual | 🔴 P0 | `cache_manager.py` | Baixo |
| `SEC-008` | Sanitização logs completa | 🔴 P0 | `pipeline.py`, `config.py` | Baixo |
| `PDF-010` | OCR paralelo | 🔴 P0 | `pdf_processor.py` | Médio |
| `PDF-011` | OCR seletivo por página | 🔴 P0 | `pdf_processor.py` | Médio |
| `CLS-006` | Patterns Agravo/Embargos | 🟡 P1 | `classifier.py` | Baixo |
| `CLS-007` | Busca em 3 janelas | 🟡 P1 | `classifier.py` | Baixo |
| `CLS-008` | Few-shot classifier LLM | 🟡 P1 | `classifier.py` | Baixo |
| `MIN-001` | Embedding semântico minutas | 🟡 P1 | `minuta_selector.py`, novo script | Alto |
| `MIN-002` | Truncamento por seção | 🟡 P1 | `minuta_selector.py` | Baixo |
| `E3-006` | Normalização aspas transcrição | 🟡 P1 | `etapa3.py` | Baixo |
| `E3-007` | Normalização espaço decisão | 🟡 P1 | `etapa3.py` | Baixo |
| `E3-008` | Redução contexto retry Etapa 3 | 🟡 P1 | `etapa3.py` | Baixo |
| `CONF-001` | Pesos confiança configuráveis | 🟡 P1 | `pipeline.py`, `config.py` | Baixo |
| `CONF-002` | Pricing via arquivo JSON | 🟡 P1 | `pipeline.py`, novo `pricing.json` | Baixo |
| `CONF-003` | Teto tokens configurável | 🟡 P1 | `llm_client.py`, `config.py` | Baixo |
| `LLM-007` | Circuit breaker API | 🟢 P2 | `llm_client.py` | Médio |
| `LLM-008` | Idempotência persistente | 🟢 P2 | `llm_client.py` | Médio |
| `PDF-012` | Suporte DOCX | 🟢 P2 | novo `document_extractor.py` | Alto |
| `OBS-005` | Métricas por tipo de caso | 🟢 P2 | `operational_dashboard.py` | Médio |
| `OBS-006` | Alerta por tipo de recurso | 🟢 P2 | `regression_alerts.py` | Baixo |

---

## 🗺️ Roadmap de Execução

```
Sprint 1 — Segurança (1 semana)
  SEC-005 → SEC-006 → SEC-007 → SEC-008

Sprint 2 — Performance OCR (1 semana)
  PDF-010 (paralelo) → PDF-011 (seletivo)

Sprint 3 — Qualidade Jurídica (1 semana)
  CLS-006 → CLS-007 → CLS-008
  E3-006 → E3-007 → E3-008

Sprint 4 — Seleção Inteligente de Minutas (2 semanas)
  MIN-001 (embedding — maior esforço)
  MIN-002 (truncamento por seção)

Sprint 5 — Configurabilidade (1 semana)
  CONF-001 → CONF-002 → CONF-003

Sprint 6 — Robustez e Escala (2 semanas)
  LLM-007 → LLM-008 → PDF-012
  OBS-005 → OBS-006
```

---

## ✅ Critérios de Conclusão desta Rodada

- [x] **DONE-01** Todos os itens 🔴 P0 implementados, testados e revisados
- [x] **DONE-02** Taxa de INCONCLUSIVO < 5% no dataset ouro após melhorias de classificação (medido por INCONCLUSIVO não esperado)
- [x] **DONE-03** OCR paralelo: redução de > 60% no tempo de processamento de PDFs escaneados (benchmark registrado)
- [x] **DONE-04** Zero dados pessoais/processuais em texto plano em DLQ ou cache
- [x] **DONE-05** Score global estimado ≥ 9.0/10 após todas as fases A e B
