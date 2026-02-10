# Copilot Jurídico — Agente de Admissibilidade Recursal (TJPR)

Sistema CLI em Python para análise de admissibilidade recursal (Recurso Especial e Extraordinário), com pipeline de 3 etapas e geração de minuta.

## Visão geral

Fluxo principal:
1. Extração e classificação dos PDFs (recurso/acórdão).
2. Etapa 1: extração estruturada da petição recursal.
3. Etapa 2: análise temática do acórdão.
4. Etapa 3: geração da minuta de admissibilidade.
5. Salvamento de minuta, relatório de auditoria e métricas.

## Requisitos

- Python 3.11+
- Chave de API OpenAI ativa
- Linux/macOS (comandos abaixo usam `bash`)

## Instalação

```bash
git clone <url-do-repositorio>
cd agente_assessores

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuração

Copie e ajuste o arquivo de ambiente:

```bash
cp .env.example .env
```

Variáveis usadas pelo projeto:
- `OPENAI_API_KEY`: chave da API (obrigatória para `processar`)
- `OPENAI_MODEL`: modelo padrão (ex.: `gpt-4o`)
- `MAX_TOKENS`: limite de tokens por chamada
- `TEMPERATURE`: temperatura padrão do modelo
- `LLM_TIMEOUT`: timeout das chamadas LLM (segundos)
- `LLM_MAX_RETRIES`: tentativas em erros transitórios
- `LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`

## Uso (CLI)

Ajuda geral:

```bash
python -m src.main --help
```

Processar PDFs:

```bash
python -m src.main processar recurso.pdf acordao.pdf
python -m src.main processar recurso.pdf acordao.pdf --formato docx
python -m src.main processar recurso.pdf acordao.pdf --modelo gpt-4o-mini --temperatura 0.1
python -m src.main processar recurso.pdf acordao.pdf --saida ./outputs_cliente_x
python -m src.main processar recurso.pdf acordao.pdf --continuar
```

Checkpoint e limpeza:

```bash
python -m src.main status
python -m src.main limpar
```

## Ajuste do prompt (`SYSTEM_PROMPT.md`)

Arquivo efetivamente lido pelo pipeline: `prompts/SYSTEM_PROMPT.md`.

Fluxo recomendado:
1. Editar `prompts/SYSTEM_PROMPT.md`.
2. Incrementar versão/data na seção de versionamento do prompt.
3. Executar ao menos 1 caso real e comparar minuta + auditoria com a versão anterior.
4. Validar impacto nos testes:
   - `python -m pytest -q`
5. Registrar no PR o que mudou no prompt e o efeito esperado.

## Saídas e estado JSON

Arquivos gerados em `outputs/` (ou no diretório de `--saida`):
- `minuta_<processo>_<timestamp>.md` (ou `.docx`)
- `auditoria_<processo>_<timestamp>.md`
- `.checkpoints/estado_<processo_id>.json` (durante execução)

Estrutura principal do checkpoint (`EstadoPipeline`):
- `documentos_entrada[]`: `filepath`, `tipo`, `num_paginas`, `num_caracteres`
- `resultado_etapa1`: dados do recurso (processo, partes, permissivo, dispositivos, etc.)
- `resultado_etapa2.temas[]`: matéria, fundamentos, base vinculante, óbices/súmulas
- `resultado_etapa3`: `minuta_completa`, `decisao`
- `metadata`: `inicio`, `fim`, `modelo_usado`, `prompt_tokens`, `completion_tokens`, `total_tokens`

## Troubleshooting

- `OPENAI_API_KEY não configurada`: revise `.env` e reabra o terminal/venv.
- `RateLimitError`: aguarde e tente novamente.
- `APITimeoutError`/`APIConnectionError`: verificar rede e aumentar `LLM_TIMEOUT`.
- `PDF inválido/corrompido`: confirme extensão `.pdf` e integridade do arquivo.
- Saída truncada (`finish_reason != stop`): aumentar `MAX_TOKENS`.

## Testes

```bash
python -m pytest -q
python -m pytest --cov=src
```

## Documentação complementar

- Documentação técnica: `docs/README.md`
- Deploy e operação: `docs/deploy.md`
- Regras para colaboração: `CONTRIBUTING.md`
- Backlog e progresso: `TASKS.md`
