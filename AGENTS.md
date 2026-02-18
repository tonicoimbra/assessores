# Repository Guidelines

## Contexto e Fontes de Verdade
- Produto: **Assessor.AI** para exame de admissibilidade recursal (TJPR).
- Fluxo principal: **Extração de PDF -> Classificação -> Etapa 1 -> Etapa 2 -> Etapa 3 -> Minuta**.
- Referências obrigatórias antes de mudanças estruturais:
  - `PRD.md` (requisitos, sprints e critérios de aceite)
  - `docs/README.md` (índice da documentação técnica)
  - `prompts/SYSTEM_PROMPT.md` (regras e comportamento do agente jurídico)
- Em caso de conflito: priorize requisitos do `PRD.md` e mantenha consistência com a implementação já existente.

## Project Structure & Module Organization
Código principal em `src/`:
- `main.py`: CLI (`processar`, `status`, `limpar`)
- `web_app.py`: interface web (Flask) para upload/processamento
- `pipeline.py`: orquestra Etapas 1-3 e métricas
- `etapa1.py`, `etapa2.py`, `etapa3.py`: lógica jurídica por etapa
- `pdf_processor.py`, `classifier.py`: ingestão e classificação de documentos
- `llm_client.py`, `model_router.py`, `token_manager.py`: integração LLM, roteamento e orçamento de tokens
- `state_manager.py`, `cache_manager.py`: checkpoint, persistência e cache
- `prompt_loader.py`: carregamento/validação do prompt
- `models.py`: modelos de dados do pipeline
- `output_formatter.py`: geração de saída (`.md` e `.docx`)

Suporte do projeto:
- `tests/`: suíte `pytest` (incluindo `tests/fixtures/`)
- `docs/`: documentação de produto, arquitetura e deploy
- `prompts/`: prompts versionados
- `outputs/`: artefatos gerados e uploads temporários da web
- `agents/`: instruções auxiliares para subagentes

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate`: criar/ativar ambiente virtual.
- `pip install -r requirements.txt`: instalar dependências.
- `python -m src.main processar arquivo1.pdf arquivo2.pdf --formato docx`: executar pipeline via CLI.
- `python -m src.main processar arquivo1.pdf arquivo2.pdf --continuar`: retomar último checkpoint.
- `python -m src.main status`: listar checkpoints.
- `python -m src.main limpar`: remover checkpoints.
- `python -m src.web_app`: subir interface web local (porta `7860` por padrão).
- `python -m pytest -q`: rodar suíte completa.
- `python -m pytest --cov=src`: rodar testes com cobertura.
- `docker compose run --rm app processar <pdf1> <pdf2>`: execução via container.

## Coding Style & Naming Conventions
- Python 3.11+ com type hints obrigatórios.
- PEP 8, funções pequenas e coesas, sem over-engineering.
- Código (identificadores/comentários técnicos) em inglês.
- Mensagens ao usuário e documentação podem ser em português.
- `snake_case` para funções/variáveis, `PascalCase` para classes, `UPPER_CASE` para constantes.
- Preferir tratamento explícito de erros e `logging`; evitar `print` fora de CLI/UI.

## Regras Funcionais do Pipeline
- Preservar ordem obrigatória: Etapa 1 -> Etapa 2 -> Etapa 3.
- Não quebrar contratos dos modelos de dados (`models.py`) sem ajustar testes e consumidores.
- Manter tolerância a falhas de PDF (fallback de extração, validações e mensagens claras).
- Alterações em prompts devem ser feitas em arquivos `.md` (`prompts/`) e não hardcoded em módulos.
- Mudanças de provedores/modelos LLM devem respeitar flags e variáveis de ambiente existentes em `config.py`.

## Testing Guidelines
- Framework: `pytest` (+ `pytest-cov`).
- Arquivos: `tests/test_*.py`, funções `test_*`.
- Espelhar comportamento por módulo (ex.: alterações em `pipeline.py` -> `tests/test_pipeline*.py`).
- Incluir testes para cenários de borda (PDF inválido/corrompido, fallback, timeout, parsing incompleto).
- Antes de PR, rodar ao menos:
  - `python -m pytest -q`
  - testes focados no módulo alterado

## Commit & Pull Request Guidelines
- Usar Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`).
- Commits atômicos, sem misturar refactor com feature não relacionada.
- PR deve conter:
  - resumo objetivo de problema/solução
  - arquivos/módulos impactados
  - evidência de teste (comando e resultado)
  - atualização de checklist em `TASKS.md`/`PRD.md` quando aplicável

## Security & Configuration Tips
- Nunca versionar `.env`, chaves reais ou documentos sensíveis.
- Configurar credenciais a partir de `.env.example` (`OPENAI_API_KEY`, ou `OPENROUTER_API_KEY` quando usado).
- Tratar `outputs/` como conteúdo gerado potencialmente sensível.
- Sanitizar logs e mensagens para não expor dados jurídicos sigilosos.
