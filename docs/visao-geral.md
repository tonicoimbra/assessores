# Visão Geral

## O que é

Sistema de análise automatizada de recursos jurídicos (Recurso Especial e Extraordinário) do TJPR. Utiliza IA (OpenAI GPT-4o) para processar PDFs de petições e acórdãos, produzindo minutas de decisão de admissibilidade.

## Problema que resolve

O exame de admissibilidade recursal é um processo manual, repetitivo e demorado. Este sistema automatiza a análise através de um pipeline de 3 etapas, reduzindo o tempo de trabalho e mantendo a qualidade jurídica.

## Pipeline de 3 Etapas

```
PDFs (upload) → Extração de Texto → Classificação → Pipeline 3 Etapas → Minuta Final
```

| Etapa | Entrada | Saída |
|-------|---------|-------|
| **Etapa 1** — Análise do Recurso | Petição (PDF) | Dados estruturados: processo, partes, dispositivos violados |
| **Etapa 2** — Análise do Acórdão | Acórdão (PDF) + resultado da Etapa 1 | Temas, fundamentos, óbices/súmulas aplicáveis |
| **Etapa 3** — Geração da Minuta | Resultados das Etapas 1 e 2 | Minuta de decisão de admissibilidade formatada |

## Escopo atual

O projeto está em **fase de planejamento**. Os documentos de requisitos (`PRD.md`) e o prompt do agente de IA (`SYSTEM_PROMPT.md`) estão definidos. A implementação ainda não foi iniciada.

## Referências

- [PRD.md](../PRD.md) — Requisitos completos com 7 sprints e 120 subtarefas
- [SYSTEM_PROMPT.md](../SYSTEM_PROMPT.md) — Prompt do agente de IA
