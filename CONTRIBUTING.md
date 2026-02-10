# Contributing Guide

Este projeto adota fluxo simples e rastreável para mudanças de código e documentação.

## Pré-requisitos

- Python 3.11+
- Ambiente virtual ativo
- Dependências instaladas com `pip install -r requirements.txt`

## Fluxo recomendado

1. Crie uma branch descritiva:
   - `feat/export-docx`
   - `fix/timeout-retry`
2. Implemente mudanças pequenas e focadas.
3. Rode testes antes de abrir PR:
   - `python -m pytest -q`
4. Atualize `TASKS.md` quando concluir subtarefas de sprint.
5. Abra PR com contexto e evidências.

## Padrões de código

- Type hints obrigatórios.
- Nomes de variáveis/funções em inglês (`snake_case`).
- Classes em `PascalCase`.
- Logging com `logging` (evite `print` em módulos de produção).
- Evite over-engineering; prefira soluções diretas e legíveis.

## Commits

Use convenção semântica (Conventional Commits):
- `feat: ...`
- `fix: ...`
- `refactor: ...`
- `test: ...`
- `docs: ...`

Exemplo:
```text
feat: adicionar exportação DOCX na CLI
```

## Pull Requests

Inclua no PR:
- objetivo da mudança
- arquivos/módulos alterados
- impacto esperado
- comandos de teste executados e resultado
- screenshots/trechos de saída (quando útil para CLI/documentação)

Checklist mínimo:
- [ ] testes relevantes passando
- [ ] documentação atualizada (README/docs) se necessário
- [ ] `TASKS.md` atualizado para tarefas concluídas

## Ajustes de prompt

Ao alterar o prompt:
- edite `prompts/SYSTEM_PROMPT.md`
- atualize versão/data no próprio arquivo
- valide em pelo menos um caso real e registre no PR o efeito observado
