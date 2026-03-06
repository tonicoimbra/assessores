# Documentação — Assessor.AI (TJPR)

Índice central da documentação do projeto de exame de admissibilidade recursal.

Fluxo principal coberto: **Extração de PDF -> Classificação -> Etapa 1 -> Etapa 2 -> Etapa 3 -> Minuta**.

## Ordem de leitura recomendada

1. [PRD.md](../PRD.md)
2. [prompts/SYSTEM_PROMPT.md](../prompts/SYSTEM_PROMPT.md)
3. [visao-geral.md](visao-geral.md)
4. [arquitetura.md](arquitetura.md)
5. [prompt-ia.md](prompt-ia.md)
6. [criterios-aceite-qualidade.md](criterios-aceite-qualidade.md)
7. [deploy.md](deploy.md)
8. [dlq_encryption.md](dlq_encryption.md)
9. [cache-retencao.md](cache-retencao.md)
10. [calibracao_confianca.md](calibracao_confianca.md)
11. [minutas-embeddings.md](minutas-embeddings.md)

## Índice dos documentos em `docs/`

| Arquivo | Foco | Quando consultar |
|---------|------|------------------|
| [visao-geral.md](visao-geral.md) | Contexto de negócio, problema e pipeline | Alinhamento rápido de produto |
| [arquitetura.md](arquitetura.md) | Arquitetura técnica, fluxo de dados e variáveis | Decisões técnicas e integração de componentes |
| [prompt-ia.md](prompt-ia.md) | Resumo operacional do prompt e regras anti-alucinação | Revisão rápida de comportamento jurídico do agente |
| [padroes-desenvolvimento.md](padroes-desenvolvimento.md) | Convenções de código, testes e critérios de done | Implementação e revisão de PR |
| [estrutura-projeto.md](estrutura-projeto.md) | Organização de diretórios e responsabilidades por módulo | Navegação de código e onboarding |
| [criterios-aceite-qualidade.md](criterios-aceite-qualidade.md) | Baseline ouro, quality gate, streak e alertas de regressão | Validação de qualidade antes de promover mudanças |
| [deploy.md](deploy.md) | Execução local, Docker, VPS e Coolify | Operação e publicação |
| [dlq_encryption.md](dlq_encryption.md) | Criptografia da Dead Letter Queue e rotação de chave | Segurança operacional e troubleshooting de DLQ |
| [cache-retencao.md](cache-retencao.md) | TTL, expiração e purge do cache de conteúdo processual | Governança de retenção e compliance operacional |
| [calibracao_confianca.md](calibracao_confianca.md) | Calibração dos pesos de confiança entre Etapas 1-3 | Ajuste de thresholds/pesos com base em casos reais |
| [minutas-embeddings.md](minutas-embeddings.md) | Indexação semântica das minutas de referência | Regenerar embeddings após importar novas minutas |
| [prompt-refinement-sprint7.md](prompt-refinement-sprint7.md) | Evidências de tuning de prompt na Sprint 7.1 | Auditoria histórica de decisões de prompt |
| [glossario.md](glossario.md) | Termos jurídicos e técnicos do domínio | Padronização de linguagem |

## Fontes de verdade e precedência

Em caso de divergência entre documentos, seguir a ordem:

1. [PRD.md](../PRD.md)
2. [prompts/SYSTEM_PROMPT.md](../prompts/SYSTEM_PROMPT.md)
3. Implementação em `src/` e testes em `tests/`
4. Documentos de apoio em `docs/`

## Documentos-raiz relacionados

| Arquivo | Descrição |
|---------|-----------|
| [PRD.md](../PRD.md) | Requisitos funcionais, sprints e critérios de aceite |
| [prompts/SYSTEM_PROMPT.md](../prompts/SYSTEM_PROMPT.md) | Prompt canônico do agente jurídico |
| [TASKS.md](../TASKS.md) | Backlog e evolução de execução |
| [CLAUDE.md](../CLAUDE.md) | Regras operacionais para assistentes de IA no repositório |
