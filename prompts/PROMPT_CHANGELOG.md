# Prompt Changelog (SemVer)

## 2.5.0 - 2026-03-12
- Refinamento baseado em comparativo de minutas (processo 0008861-22.2024.8.16.0160).
- Etapa 1: vedação explícita de incluir conteúdo do acórdão ou das contrarrazões na saída.
- Etapa 2: regra de prioridade de acórdão mais recente (embargos de declaração > apelação) quando o tema recursal for decidido nos embargos.
- Etapa 2: regra da Súmula `83/STJ` por alinhamento jurisprudencial — quando o acórdão citar/aplicar jurisprudência do STJ/STF convergente com o recorrido.

## 2.4.0 - 2026-03-12
- Auditoria de integridade contra `prompt_ref_copilot/` e prompts modulares.
- Adição da Súmula `123/STJ` ausente no catálogo do `SYSTEM_PROMPT.md` (legado).
- Regra de expansão de siglas adicionada nas convenções de redação.
- Vedação explícita de aspas nas Seções I e III da Etapa 3.
- Proteção contra alteração de estilo no texto-base da Etapa 1 (Seção I → Etapa 3).
- Refinamento da regra de segmentação temática na Etapa 2 (alinhado com `dev_etapa2.md`).
- Regra de fallback por marcador para extração insegura de tema/óbice (Etapa 2).

## 2.3.0 - 2026-03-11
- Consolidação crítica dos materiais em `prompt_ref_copilot/` no prompt canônico e nos prompts modulares.
- Inclusão de hierarquia explícita de instruções e regra anti-prompt-injection para textos vindos dos PDFs.
- Vedação expressa de consulta a SharePoint, internet e outras fontes externas não fornecidas na execução.
- Reforço da disciplina de prova textual, com exigência de aderência literal e tratamento de ambiguidades por marcador.
- Etapa 2 refinada com critérios mais rígidos para segmentação por tema, classificação da natureza do fundamento e aplicação dos óbices.
- Etapa 3 refinada com regra decisória fechada para `admito`, `inadmito` e `admito parcialmente`, proibindo fundamento novo na Seção III.

## 2.2.0 - 2026-03-04
- Atualização do `CLASSIFICATION_PROMPT` com few-shot para classificador LLM.
- Inclusão de 2 exemplos de `RECURSO` e 2 exemplos de `ACORDAO`.
- Inclusão de casos limítrofes explícitos: `Embargos de Declaração` e `Agravo Regimental`.
- Reforço de instrução de saída estritamente em JSON para reduzir ambiguidade.

## 2.1.0 - 2026-02-13
- Migração operacional para estratégia modular por etapa (`system_base`, `dev_etapa1`, `dev_etapa2`, `dev_etapa3`).
- Assinatura de prompt (profile, version, hash SHA-256) registrada em `EstadoPipeline`.
- Validação de contrato de prompt antes do pipeline (fail-closed).
- Fallback minimalista não silencioso; bloqueado por padrão.

## 2.0.0 - 2026-02-12
- Prompt monolítico legado em `SYSTEM_PROMPT.md`.
- Regras gerais unificadas para Etapas 1-2-3.

## Política de Rollback
- Rollback rápido para prompt legado:
  - definir `PROMPT_STRATEGY=legacy` no `.env`.
  - garantir `prompts/SYSTEM_PROMPT.md` presente e íntegro.
- Modo padrão recomendado:
  - `PROMPT_STRATEGY=modular`.
