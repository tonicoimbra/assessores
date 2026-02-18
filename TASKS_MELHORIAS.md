# TASKS_MELHORIAS — Confiabilidade Máxima (Extração, Análise e Decisão)

> Objetivo: elevar o Assessor.AI para um modo de operação **evidence-first**, com validação estrita, comportamento fail-closed e rastreabilidade completa.

## Status de Execução (Lote Atual)

- [x] `CLS-002` Invariantes de entrada no pipeline (1 recurso, >=1 acórdão) implementadas com validação estrita.
- [x] `CLS-003` Pipeline interrompe com erro orientado quando invariantes de classificação falham.
- [x] `LLM-001` `finish_reason != stop` agora aciona retry automático e falha explícita se persistir truncamento.
- [x] Hardening adicional: validações fail-closed obrigatórias por etapa (Etapas 1, 2 e 3) no orquestrador.
- [x] Hardening adicional: truncamento com preservação de início/fim do texto para reduzir perda de contexto decisivo.
- [x] `PDF-002` OCR automático opcional para baixa extração, com fallback seguro e feature flag.
- [x] `PDF-005` Score de qualidade de extração (`quality_score`) em faixa `[0, 1]`.
- [x] `PDF-008` Metadados ampliados de extração (`raw_text_by_page`, `clean_text_by_page`, `pages_with_ocr`, `ocr_aplicado`).
- [x] `E1-001` Etapa 1 com tentativa primária de saída JSON estruturada (com retry reforçado) e fallback legado seguro.
- [x] `E2-001` Etapa 2 com tentativa primária de saída JSON estruturada (com retry reforçado) e fallback legado seguro.
- [x] `E3` Etapa 3 com tentativa primária de saída JSON estruturada (com retry reforçado) e fallback legado seguro.
- [x] `E3-001` Etapa 3 separada entre motor determinístico de decisão e LLM para redação da minuta.
- [x] `E3-003` Validação de coerência decisão x minuta com log de divergência e prevalência determinística.
- [x] `CLS-004` Evidências da classificação registradas por documento (método, scores, padrões e snippets).
- [x] `E1-002` Evidência por campo crítico na Etapa 1 (citação literal, página e âncora), com fallback determinístico local.
- [x] `E1-003` Verificador independente pós-LLM da Etapa 1 implementado, confirmando campos críticos no texto-fonte.
- [x] `E1-004` Retry orientado por erro na Etapa 1 (campo faltante, sem lastro de evidência e inconsistência semântica).
- [x] `E1-005` Etapa 1 marca `INCONCLUSIVA` quando inválida após retries e bloqueia execução da Etapa 2.
- [x] `E1-006` Etapa 1 remove dependência primária de regex na saída livre (normalização JSON-first; regex apenas fallback final).
- [x] `AUD-005` Motivo de bloqueio padronizado para casos inconclusivos persistido em metadata/etapa3/auditoria.
- [x] `PRM-002` Assinatura de prompt (profile + versão + hash SHA-256) persistida no estado/auditoria.
- [x] `PRM-001` Fallback minimalista de prompt não é mais silencioso (bloqueado por padrão em produção).
- [x] `PRM-003` Validação de compatibilidade prompt-contrato antes do pipeline (modo fail-closed).
- [x] `PRM-004` Suíte de regressão canônica de prompts adicionada ao pytest.
- [x] `PRM-005` Changelog semântico de prompt + rollback rápido via `PROMPT_STRATEGY`.
- [x] `PRIO-06` Logging estruturado JSON com correlação por `processo_id` e `execucao_id`.
- [x] `OBS-001` Instrumentação por etapa com eventos estruturados (`EVENTO_JSON`).
- [x] `PRIO-02` Dead-letter queue para falhas não-transientes com snapshot completo (erro, estado, métricas e contexto).
- [x] `PRIO-04` Score de confiança por campo/tema com política de escalonamento para revisão humana.
- [x] `PRIO-05` Chunking semântico com overlap controlado e `coverage_map` auditável por etapa.
- [x] `PRIO-07` Suíte adversarial (PDF corrompido, escaneado ruim, ambiguidades).
- [x] `PRIO-09` Dashboard operacional (latência, erro por etapa, custo, tokens).
- [x] `PRIO-10` Cache multi-nível por hash de entrada e versão de prompt/modelo.
- [x] `PRIO-12` Validação cruzada adicional da classificação com verificador barato.
- [x] `PRIO-11` Pré-processamento avançado de imagem para OCR (deskew/denoise/binarização).

## Backlog Prioritário (Revisão Independente MCP)

- [x] `PRIO-01` Evidência rastreável por campo/tema (citação literal + página + âncora).
- [x] `PRIO-02` Dead-letter queue para casos falhos não-transientes com snapshot completo.
- [x] `PRIO-03` Dataset ouro versionado + gate CI de regressão E2E.
- [x] `PRIO-04` Score de confiança por campo/tema com política de escalonamento.
- [x] `PRIO-05` Chunking semântico com overlap controlado e cobertura auditável.
- [x] `PRIO-06` Logging estruturado JSON com correlação por `processo_id`/execução.
- [x] `PRIO-07` Suíte adversarial (PDF corrompido, escaneado ruim, ambiguidades).
- [x] `PRIO-08` Rationale estruturado de decisão antes da redação da minuta.
- [x] `PRIO-09` Dashboard operacional (latência, erro por etapa, custo, tokens).
- [x] `PRIO-10` Cache multi-nível por hash de entrada e versão de prompt/modelo.
- [x] `PRIO-11` Pré-processamento avançado de imagem para OCR (deskew/denoise/binarização).
- [x] `PRIO-12` Validação cruzada adicional da classificação com verificador barato.

## 0) Metas de Qualidade (gates obrigatórios)

- [x] **MQ-001** Definir baseline em dataset ouro com métricas por etapa.
- [x] **MQ-002** Definir alvo de qualidade para produção:
- [x] `Extração PDF` >= 99.5% de páginas com texto útil.
- [x] `Etapa 1` >= 98% F1 em campos críticos (`numero_processo`, `recorrente`, `especie_recurso`).
- [x] `Etapa 2` >= 97% F1 em temas/óbices.
- [x] `Decisão final` >= 99% de concordância com gabarito humano.
- [x] **MQ-003** Definir política fail-closed: sem evidência suficiente, não emitir decisão conclusiva.
- [x] **MQ-004** Publicar critérios formais de aceite em `docs/`.

## 1) Extração de PDF (P0)

- [x] **PDF-001** Implementar pipeline de extração em camadas em `src/pdf_processor.py`:
- [x] `PyMuPDF` -> `pdfplumber` -> `OCR`.
- [x] **PDF-002** Adicionar OCR automático para PDFs escaneados (Tesseract/PaddleOCR), com feature flag.
- [x] **PDF-003** Persistir texto bruto por página antes da limpeza (`raw_text_by_page`).
- [x] **PDF-004** Persistir texto limpo por página (`clean_text_by_page`), sem perder mapeamento de origem.
- [x] **PDF-005** Incluir score de qualidade por página e por documento (`ocr_confidence`, `noise_ratio`).
- [x] **PDF-006** Revisar limpeza para não remover conteúdo jurídico válido em linhas curtas repetidas.
- [x] **PDF-007** Salvar hashes por página para detectar variações/reprocessamento.
- [x] **PDF-008** Expor no resultado de extração: engine, páginas com fallback, páginas OCR e confidence.
- [x] **PDF-009** Bloquear continuidade quando qualidade da extração for insuficiente (threshold configurável).

## 2) Classificação de Documento (P0)

- [ ] **CLS-001** Tornar a classificação determinística com score composto:
- [ ] heurística + LLM + regras de consistência.
- [x] **CLS-002** Exigir invariantes de entrada no pipeline:
- [x] exatamente 1 `RECURSO`.
- [x] >= 1 `ACORDAO`.
- [x] **CLS-003** Se invariantes falharem, parar pipeline com erro orientado e ação recomendada.
- [x] **CLS-004** Registrar evidências da classificação (trechos + padrões acionados).
- [ ] **CLS-005** Adicionar modo de revisão manual para documentos ambíguos.

## 3) Etapa 1 — Extração Estruturada do Recurso (P0)

- [x] **E1-001** Migrar saída de texto livre para JSON estrito validado por schema/Pydantic.
- [x] **E1-002** Para cada campo crítico, exigir evidência:
- [x] citação literal.
- [x] página de origem.
- [x] offset/âncora.
- [x] **E1-003** Implementar verificador independente pós-LLM que confirma cada campo no texto fonte.
- [x] **E1-004** Implementar retry orientado por erro:
- [x] campos faltantes.
- [x] campo sem lastro.
- [x] inconsistência semântica.
- [x] **E1-005** Se após retries ainda inválido, marcar etapa como `INCONCLUSIVA` e bloquear Etapa 2.
- [x] **E1-006** Remover dependência primária de regex em saída livre.

## 4) Etapa 2 — Análise do Acórdão (P0)

- [x] **E2-001** Migrar para JSON estrito com schema de temas.
- [x] **E2-002** Exigir evidência por tema:
- [x] matéria controvertida.
- [x] conclusão/fundamentos.
- [x] óbices/súmulas.
- [x] trecho literal com página.
- [x] **E2-003** Validar súmulas por taxonomia oficial versionada.
- [x] **E2-004** Validar que cada óbice consta no texto fonte (string ou variante normalizada).
- [x] **E2-005** Deduplicação semântica robusta de temas entre chunks.
- [x] **E2-006** Bloquear Etapa 3 se tema essencial estiver sem evidência.

## 5) Etapa 3 — Decisão e Minuta (P0)

- [x] **E3-001** Separar decisão em dois componentes:
- [x] `motor_determinístico` de admissibilidade (regras explícitas).
- [x] `gerador de minuta` apenas para redação.
- [x] **E3-002** Fazer o LLM retornar estrutura de decisão antes da minuta:
- [x] decisão (`ADMITIDO`/`INADMITIDO`/`INCONCLUSIVO`).
- [x] fundamentos.
- [x] itens de evidência usados.
- [x] **E3-003** Validar coerência entre decisão estruturada e minuta textual.
- [x] **E3-004** Não permitir minuta final quando decisão = `INCONCLUSIVO` sem aviso explícito.
- [x] **E3-005** Implementar regra de precedência para conflito entre evidências.

## 6) Contexto, Chunking e Perda de Informação (P0)

- [ ] **CTX-001** Substituir truncamento linear por chunking semântico com cobertura total.
- [ ] **CTX-002** Garantir preservação de início, meio e fim do documento em qualquer redução.
- [ ] **CTX-003** Implementar rastreio de cobertura por chunk (`coverage_map`).
- [ ] **CTX-004** Alertar e bloquear quando cobertura útil < threshold.
- [ ] **CTX-005** Adicionar estratégia map-reduce com reconciliação determinística.

## 7) Cliente LLM e Robustez de Chamada (P0)

- [x] **LLM-001** Tratar `finish_reason != stop` como erro recuperável com retry automático.
- [ ] **LLM-002** Incluir validação de schema já na resposta (quando suportado).
- [ ] **LLM-003** Implementar idempotência por `request_id` e reexecução segura.
- [x] **LLM-004** Isolar cache por versão de prompt, modelo e schema.
- [ ] **LLM-005** Registrar latência, retries, truncamentos e taxa de erro por etapa.
- [ ] **LLM-006** Opcional: consenso N=2 para campos críticos em casos de baixa confiança.

## 8) Prompt e Governança de Versão (P1)

- [x] **PRM-001** Eliminar fallback silencioso para prompt minimalista em produção.
- [x] **PRM-002** Assinar prompt com versão + hash e gravar no `EstadoPipeline`.
- [x] **PRM-003** Validar compatibilidade prompt-schema antes de iniciar pipeline.
- [x] **PRM-004** Criar suíte de regressão de prompt com casos canônicos.
- [x] **PRM-005** Definir changelog semântico de prompt e rollback rápido.

## 9) Estado, Auditoria e Explicabilidade (P1)

- [x] **AUD-001** Estender `models.py` para armazenar evidências por campo e por tema.
- [x] **AUD-002** Gerar trilha de auditoria em JSON estruturado além do markdown.
- [x] **AUD-003** Persistir snapshot de entradas e validações por etapa.
- [x] **AUD-004** Adicionar indicador de confiança por etapa e confiança global.
- [x] **AUD-005** Adicionar “motivo de bloqueio” padronizado para casos inconclusivos.

## 10) Testes e Qualidade (P0)

- [x] **TST-001** Criar dataset ouro versionado em `tests/fixtures/golden/`.
- [x] **TST-002** Adicionar testes de contrato de schema (Etapa 1/2/3).
- [x] **TST-003** Adicionar testes de regressão com PDFs escaneados reais.
- [x] **TST-004** Adicionar testes de mutação em regras críticas de decisão.
- [x] **TST-005** Adicionar testes property-based para parsers e normalização.
- [x] **TST-006** Adicionar testes E2E com validação de evidência obrigatória.
- [x] **TST-007** Criar benchmark contínuo de qualidade (CI) com gate de aprovação.
- [x] **TST-008** Bloquear merge quando qualquer métrica crítica cair.

## 11) Observabilidade e Operação (P1)

- [x] **OBS-001** Instrumentar logs estruturados por `processo_id` e `etapa`.
- [x] **OBS-002** Exportar métricas operacionais:
- [x] taxa de erro por etapa.
- [x] taxa de `INCONCLUSIVO`.
- [x] retrabalho/retry.
- [x] cobertura de evidência.
- [x] **OBS-003** Implementar dashboard de qualidade por build.
- [x] **OBS-004** Alertas automáticos para regressão de extração/decisão.

## 12) Segurança e Conformidade (P1)

- [ ] **SEC-001** Sanitizar logs para remover dados sensíveis de peças processuais.
- [ ] **SEC-002** Implementar política de retenção para `outputs/` e checkpoints.
- [ ] **SEC-003** Adicionar controle de acesso para download de arquivos na web.
- [ ] **SEC-004** Revisar `.env`/segredos e endurecer validações de ambiente.

## 13) Roadmap de Execução

- [ ] **Fase A (P0 imediato)**: `PDF-*`, `CLS-*`, `E1-*`, `E2-*`, `E3-*`, `CTX-*`, `LLM-*`, `TST-*`.
- [ ] **Fase B (P1)**: `PRM-*`, `AUD-*`, `OBS-*`, `SEC-*`.
- [ ] **Fase C (otimização)**: consenso multi-modelo, calibração de confiança e redução de custo sem perda de qualidade.

## 14) Critérios de Pronto para Produção

- [ ] **PRD-READY-001** Todos os itens P0 concluídos e testados.
- [ ] **PRD-READY-002** Gates de qualidade atendidos por 3 execuções consecutivas no CI.
- [ ] **PRD-READY-003** 0 falhas críticas de evidência em dataset ouro.
- [ ] **PRD-READY-004** Política fail-closed ativa e validada em cenários de erro.
- [ ] **PRD-READY-005** Auditoria completa disponível para 100% dos casos processados.
