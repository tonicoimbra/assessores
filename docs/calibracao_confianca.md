# Calibração de Confiança do Pipeline

Este documento define como calibrar os pesos de confiança do score global do pipeline.

## Variáveis de ambiente

Configure os pesos no `.env`:

- `CONFIDENCE_WEIGHT_ETAPA1`
- `CONFIDENCE_WEIGHT_ETAPA2`
- `CONFIDENCE_WEIGHT_ETAPA3`

Regras obrigatórias:

- Cada peso deve estar entre `0` e `1`.
- A soma dos 3 pesos deve ser `1.0` (tolerância `+- 0.001`).

Defaults atuais:

- Etapa 1: `0.35`
- Etapa 2: `0.35`
- Etapa 3: `0.30`

## Procedimento recomendado

1. Monte um conjunto de casos reais revisados (amostra estratificada por tipo recursal).
2. Execute o pipeline e colete para cada caso:
   - score da Etapa 1
   - score da Etapa 2
   - score da Etapa 3
   - decisão final (correta/incorreta)
3. Simule combinações de pesos mantendo soma `1.0`.
4. Selecione os pesos que maximizam a métrica de qualidade (ex.: acurácia final e taxa de inconclusivo controlada).
5. Atualize os pesos no `.env` e rode regressão (`pytest`) antes de promover para produção.

## Exemplo

```env
CONFIDENCE_WEIGHT_ETAPA1=0.30
CONFIDENCE_WEIGHT_ETAPA2=0.40
CONFIDENCE_WEIGHT_ETAPA3=0.30
```

## Validação em inicialização

A validação de ambiente (`src/config.py::validate_environment_settings`) bloqueia configurações inválidas quando:

- algum peso estiver fora do intervalo `[0, 1]`
- a soma dos pesos for diferente de `1.0` acima da tolerância

Isso evita cálculos inconsistentes no score global do pipeline.
