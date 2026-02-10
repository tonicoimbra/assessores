# Padrões de Desenvolvimento

Definidos no [`CLAUDE.md`](../CLAUDE.md) e no [`PRD.md`](../PRD.md).

## Linguagem e Stack

- **Python 3.11+** (mínimo), com suporte para 3.12
- **Type hints obrigatórios** em todo o código
- Testes com **pytest**
- Commits seguindo **convenção semântica**: `feat:`, `fix:`, `refactor:`

## Estrutura de diretórios

```
src/         → código principal
tests/       → testes
docs/        → documentação
prompts/     → prompt do agente (SYSTEM_PROMPT.md)
outputs/     → minutas geradas
```

## Regras de código

- Código auto-documentado e conciso, sem over-engineering
- Variáveis e comentários de código em **inglês**
- Respostas ao usuário e documentação em **português**

## Assistentes de IA

O projeto usa configuração `.agent/` (Antigravity Kit) para assistentes de IA. Regras específicas:

- Respostas sempre em português
- Consultar `CLAUDE.md` antes de qualquer implementação
- Não ler `node_modules/`, `.venv/`, `__pycache__/`, `.git/`

## Critérios de aceite (Definition of Done)

Uma tarefa é considerada concluída quando:

1. Implementa exatamente o escopo descrito na subtarefa
2. Testes unitários passam (quando aplicável)
3. Sem erros de linting (`ruff` ou `flake8`)
4. Funcionalidade verificada manualmente com pelo menos 1 caso real
5. Checklist marcado com `[x]` no PRD
