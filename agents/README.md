# Agentes de IA — Assessor.AI

> Agentes especializados na stack real do projeto para produção de código com maior assertividade.

---

## Agentes disponíveis

| Agente | Arquivo | Foco | Quando usar |
|--------|---------|------|-------------|
| **Backend** | [backend.md](backend.md) | Flask, Python, pipeline de IA, PDF/LLM | Etapas jurídicas, integração LLM, robustez e performance |
| **Frontend** | [frontend.md](frontend.md) | Jinja/Flask templates, CSS, JavaScript | Upload UI, feedback visual, usabilidade e responsividade |
| **QA / Tester** | [qa-tester.md](qa-tester.md) | pytest, Flask test client, Playwright | Regressão funcional, integração e E2E |

---

## Como usar

Referencie o agente relevante ao início da tarefa:

```text
@agents/backend.md — Ajuste a classificação e checkpoint do pipeline
```

Para tarefas ponta a ponta, use esta ordem:

1. **Backend** — implementar regra/serviço e contrato de dados.
2. **Frontend** — refletir mudanças na interface e fluxo do usuário.
3. **QA/Tester** — validar regressão unitária, integração e E2E.

---

## Playbook MCP (eficiência + assertividade)

1. **Descoberta técnica (Context7)**
   - Consultar docs oficiais antes de alterar APIs de Flask, OpenAI SDK, PyMuPDF, Pydantic.
   - Resultado esperado: implementação correta na primeira tentativa.

2. **Implementação backend/frontend**
   - Aplicar mudança mínima no módulo certo (`src/` ou `templates/static`).
   - Preservar contratos dos modelos e do pipeline 3 etapas.

3. **Validação de interface (Playwright)**
   - Executar smoke E2E no fluxo: upload -> processar -> resultado -> download.
   - Capturar screenshot em caso de erro para diagnóstico rápido.

4. **Gate de qualidade antes de merge**
   - `python -m pytest -q`
   - testes focados no módulo alterado
   - verificação manual breve do fluxo web quando houver impacto visual

---

## Critérios de qualidade por entrega

- Mudança com impacto restrito ao escopo solicitado.
- Cobertura de caminho feliz + caminho de erro.
- Sem regressão no pipeline jurídico (Etapa 1 -> 2 -> 3).
- Evidência de teste anexada na PR (comando e resultado).
