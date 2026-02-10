# Estrutura do Projeto

## Estado atual

O projeto está em fase de planejamento. Arquivos existentes na raiz:

```
agente_assessores/
├── .agent/              # Configurações do Antigravity Kit (agentes/skills de IA)
├── docs/                # Esta documentação
├── CLAUDE.md            # Regras para assistentes de IA
├── PRD.md               # Product Requirements Document
└── SYSTEM_PROMPT.md     # Prompt do agente de admissibilidade
```

## Estrutura planejada (conforme PRD)

```
copilot-juridico/
├── src/
│   ├── __init__.py
│   ├── main.py              # Ponto de entrada CLI
│   ├── config.py            # Configurações e variáveis de ambiente
│   ├── pdf_processor.py     # Extração de texto de PDFs
│   ├── classifier.py        # Classificação de documentos
│   ├── pipeline.py          # Orquestrador das 3 etapas
│   ├── etapa1.py            # Lógica da Etapa 1
│   ├── etapa2.py            # Lógica da Etapa 2
│   ├── etapa3.py            # Lógica da Etapa 3
│   ├── prompt_loader.py     # Carregamento do prompt externo
│   ├── output_formatter.py  # Formatação da saída final
│   └── models.py            # Dataclasses/Pydantic models
├── prompts/
│   └── SYSTEM_PROMPT.md     # Prompt principal
├── tests/
│   ├── __init__.py
│   ├── test_pdf_processor.py
│   ├── test_classifier.py
│   ├── test_etapa1.py
│   ├── test_etapa2.py
│   ├── test_etapa3.py
│   └── fixtures/            # PDFs de teste
├── outputs/                 # Minutas geradas
├── .env.example
├── requirements.txt
└── README.md
```

## Descrição dos módulos planejados

| Módulo | Responsabilidade |
|--------|-----------------|
| `main.py` | CLI com argparse/typer. Flags: `--modelo`, `--temperatura`, `--saida`, `--verbose` |
| `config.py` | Carregamento de `.env`, validação da API key, constantes |
| `pdf_processor.py` | Extração de texto com PyMuPDF, fallback pdfplumber, limpeza de texto |
| `classifier.py` | Classificação de documentos (heurística textual → fallback LLM) |
| `pipeline.py` | Orquestrador que executa Etapas 1→2→3 em sequência |
| `etapa1.py` | Análise da petição do recurso |
| `etapa2.py` | Análise do acórdão |
| `etapa3.py` | Geração da minuta |
| `prompt_loader.py` | Leitura e cache do SYSTEM_PROMPT.md, extração de seções por etapa |
| `output_formatter.py` | Formatação markdown, salvamento, relatório de auditoria |
| `models.py` | Pydantic models para todos os dados do pipeline |
