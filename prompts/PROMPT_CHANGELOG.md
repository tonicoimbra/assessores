# Prompt Changelog (SemVer)

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
