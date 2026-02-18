# Prompt Changelog (SemVer)

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
