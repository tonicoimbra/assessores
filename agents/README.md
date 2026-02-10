# Agentes de IA — Copilot Jurídico

> Agentes especializados na stack do projeto para produção de código.

---

## Agentes disponíveis

| Agente | Arquivo | Foco | Quando usar |
|--------|---------|------|-------------|
| **Backend** | [backend.md](backend.md) | Django, Python, OpenAI API, PDF processing | Models, views, services, pipeline de IA, API endpoints |
| **Frontend** | [frontend.md](frontend.md) | Django Templates, TailwindCSS, JavaScript | Templates HTML, estilos, interatividade, UI/UX |
| **QA / Tester** | [qa-tester.md](qa-tester.md) | Testes automatizados, Playwright, pytest | Testes unitários, integração, E2E, validação visual |

---

## Como usar

Referencie o agente relevante ao início da tarefa:

```
@agents/backend.md — Implemente a view de processamento da análise
```

Para tarefas que cruzam domínios (ex: nova feature completa), use os agentes na ordem:

1. **Backend** → criar models, views, services
2. **Frontend** → criar templates e estilos
3. **QA/Tester** → testar a feature completa
