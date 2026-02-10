# Projeto: Agente de Admissibilidade Recursal (TJPR)

## Visão Geral
Sistema de análise automatizada de recursos jurídicos (Recurso Especial e Extraordinário) do TJPR.
Pipeline de 3 etapas: Análise do Recurso → Análise do Acórdão → Geração da Minuta.

## Stack
- Python 3.11+
- OpenAI API (GPT-4o)
- PyMuPDF (fitz) + pdfplumber (extração de PDF)
- Pydantic (modelos de dados)
- python-dotenv (configuração)
- rich (CLI)
- pytest (testes)
- Linux Mint

## Regras
- Respostas em português
- Código com type hints obrigatórios
- Variáveis e comentários de código em inglês
- Testes com pytest
- Commits semânticos (feat:, fix:, refactor:)
- Temperatura da IA: 0.1 (conservador)

## Estrutura
- src/ → código principal (pipeline, etapas, modelos, CLI)
- tests/ → testes (unitários e integração)
- tests/fixtures/ → PDFs de teste
- prompts/ → SYSTEM_PROMPT.md (prompt do agente)
- outputs/ → minutas geradas
- docs/ → documentação do projeto

## Arquivos-chave
- PRD.md → requisitos, sprints e tarefas
- SYSTEM_PROMPT.md → prompt do agente de IA (iterável sem alterar código)
- docs/README.md → índice da documentação
- agents/README.md → índice dos agentes de IA (backend, frontend, QA)

## NÃO ler
- node_modules/
- .venv/
- __pycache__/
- .git/