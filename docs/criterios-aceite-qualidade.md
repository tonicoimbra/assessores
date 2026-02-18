# Critérios Formais de Aceite e Qualidade

## Objetivo

Definir critérios objetivos para promoção do pipeline a produção, com gates mensuráveis e política fail-closed.

## Baseline obrigatório (MQ-001)

- Fonte: dataset ouro versionado em `tests/fixtures/golden/`
- Geração: `python -m src.main baseline --entrada tests/fixtures/golden --saida outputs`
- Artefatos:
- `baseline_dataset_ouro_*.json`
- `baseline_dataset_ouro_*.md`

## Alvos de qualidade para produção (MQ-002)

Os seguintes thresholds são avaliados pelo comando de gate:

1. `extraction_useful_pages_rate >= 0.995`
2. `etapa1_critical_fields_accuracy >= 0.980`
3. `etapa2_proxy_f1 >= 0.970`
4. `etapa3_decisao_accuracy >= 0.990`
5. `critical_evidence_failures_zero >= 1.000` (nenhum caso com falha crítica de evidência)

Observação:
- `etapa2_proxy_f1` é uma aproximação operacional calculada a partir de acurácia de contagem de temas e acurácia de óbice esperado no dataset ouro.

## Política fail-closed (MQ-003)

O pipeline deve bloquear conclusão quando faltarem evidências críticas ou quando houver inconsistência estrutural:

1. Etapa 1 inconclusiva bloqueia Etapa 2.
2. Etapa 2 inválida bloqueia Etapa 3.
3. Decisão `INCONCLUSIVO` exige aviso explícito e motivo padronizado.
4. Sem evidência suficiente, não emitir decisão conclusiva.

Cobertura operacional:
- Em qualquer erro de execução (incluindo bloqueios fail-closed), o handler global gera auditoria emergencial (`auditoria_*.md`, `auditoria_*.json`, `snapshot_execucao_*.json`) para manter rastreabilidade completa.

## Gate automatizado

Executar:

```bash
python -m src.main quality-gate --baseline-dir outputs --saida outputs
```

Saída:

- `quality_gate_report_*.json`
- exit code `0`: aprovado
- exit code `2`: reprovado

## CI

O workflow `golden-regression.yml` executa:

1. regressão ouro E2E
2. geração de baseline
3. avaliação de gate de qualidade
4. alertas automáticos de regressão de extração/decisão

Se o gate reprovar, o job falha.

## Alertas automáticos de regressão (OBS-004)

Executar:

```bash
python -m src.main alerts --baseline-dir outputs --saida outputs
```

Comportamento:

- compara baseline atual com baseline anterior quando disponível;
- sempre verifica thresholds mínimos absolutos de extração/decisão;
- gera `regression_alert_report_*.json`;
- exit code `2` quando detectar regressão crítica.

## Dashboard operacional por build (OBS-002/OBS-003)

Executar:

```bash
python -m src.main dashboard --entrada outputs --saida outputs
```

Métricas exportadas:

1. taxa de erro por etapa (`etapa1`, `etapa2`, `etapa3`)
2. taxa de `INCONCLUSIVO`
3. retrabalho/retry (`llm_calls_truncadas_total` e taxa por chamada LLM)
4. cobertura de evidência (`campos_cobertos` / `campos_avaliados`)

Rastreabilidade de build:

- payload inclui `provider`, `build_id`, `commit_sha` e `branch` (quando disponíveis em ambiente CI).
