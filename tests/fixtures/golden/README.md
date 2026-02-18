# Dataset Ouro (Golden) — Regressão E2E

Este diretório guarda casos canônicos versionados usados como gate de regressão E2E.

## Convenções

- Versão por pasta: `v1/`, `v2/`, ...
- Um caso por arquivo JSON: `case_*.json`
- Campos obrigatórios do caso:
  - `dataset_version`
  - `case_id`
  - `inputs.pdfs[]` com `filename`, `tipo`, `texto`
  - `mock_pipeline_results.etapa1/etapa2/etapa3`
  - `expected` (decisão e asserts mínimos)

## Objetivo do gate

- Detectar regressões de orquestração e contratos do pipeline.
- Garantir estabilidade de decisão para casos canônicos.
- Não depender de API externa (teste determinístico e rápido).

## Baseline de qualidade (MQ-001)

Para gerar baseline consolidado por etapa:

```bash
python -m src.main baseline --entrada tests/fixtures/golden --saida outputs
```
