# Copilot Jurídico — Agente de Admissibilidade Recursal (TJPR)

Sistema de análise automatizada de Recurso Especial e Extraordinário do TJPR usando IA.

## O que faz

Recebe PDFs de petições recursais e acórdãos, e produz minutas de decisão de admissibilidade em 3 etapas:

1. **Etapa 1** — Extração de dados da petição do recurso
2. **Etapa 2** — Análise do acórdão recorrido
3. **Etapa 3** — Geração da minuta de decisão

## Setup

### Pré-requisitos

- Python 3.11+
- Chave de API da OpenAI

### Instalação

```bash
# Clonar o repositório
git clone <url-do-repositorio>
cd agente_assessores

# Criar e ativar ambiente virtual
python -m venv .venv
source .venv/bin/activate

# Instalar dependências
pip install -r requirements.txt

# Configurar variáveis de ambiente
cp .env.example .env
# Editar .env com sua OPENAI_API_KEY
```

### Uso

```bash
# Processar documentos (será implementado na Sprint 6)
python -m src.main processar documento1.pdf documento2.pdf

# Ver status do último processamento
python -m src.main status

# Limpar checkpoints
python -m src.main limpar
```

## Estrutura

```
src/                     # Código principal
├── main.py              # Ponto de entrada CLI
├── config.py            # Configurações e variáveis de ambiente
├── models.py            # Modelos de dados (Pydantic)
├── pdf_processor.py     # Extração de texto de PDFs
├── classifier.py        # Classificação de documentos
├── pipeline.py          # Orquestrador das 3 etapas
├── etapa1.py            # Análise do recurso
├── etapa2.py            # Análise do acórdão
├── etapa3.py            # Geração da minuta
├── prompt_loader.py     # Carregamento do prompt externo
└── output_formatter.py  # Formatação da saída
prompts/                 # Prompt do agente de IA
tests/                   # Testes (pytest)
outputs/                 # Minutas geradas
docs/                    # Documentação do projeto
```

## Testes

```bash
pytest
pytest --cov=src
```

## Documentação

Ver [docs/README.md](docs/README.md) para a documentação completa do projeto.

## Licença

Uso interno.
