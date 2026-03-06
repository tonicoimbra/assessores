# Embeddings de Minutas de Referência

Este guia descreve como gerar e atualizar o índice semântico utilizado por `src/minuta_selector.py`.

## Objetivo

Quando `minutas_referencia/embeddings.pkl` está presente, a seleção de minuta usa:

- similaridade de cosseno (`0.7`)
- score linear de metadados (`0.3`)

Se o arquivo não existir (ou a dependência não estiver instalada), o sistema mantém fallback para o score linear.

## Dependência

No ambiente virtual do projeto:

```bash
pip install -r requirements.txt
```

## Gerar embeddings

Após importar ou atualizar minutas em `minutas_referencia/textos/*.txt`, execute:

```bash
python3 scripts/indexar_minutas_embeddings.py
```

Com parâmetros opcionais:

```bash
python3 scripts/indexar_minutas_embeddings.py \
  --model paraphrase-multilingual-MiniLM-L12-v2 \
  --batch-size 16 \
  --textos-dir minutas_referencia/textos \
  --output minutas_referencia/embeddings.pkl
```

## Recarregar em runtime

Se o processo já estiver em execução e você regenerar o arquivo:

```python
from src.minuta_selector import recarregar_embeddings

recarregar_embeddings()
```

## Fluxo recomendado após novas minutas

1. Importar/atualizar textos (`scripts/importar_minutas.py`).
2. Regerar embeddings (`scripts/indexar_minutas_embeddings.py`).
3. Reiniciar aplicação ou chamar `recarregar_embeddings()`.
