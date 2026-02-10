# Sprint 7.1 — Refinamento do Prompt

## 1) Casos executados (7.1.1)

Foram executados **6 casos reais** com chamada à API e pipeline completo (Etapas 1, 2 e 3), com evidências em:
- `outputs/prompt_refinement_sprint7/baseline_report.json`
- `outputs/prompt_refinement_sprint7/caso_01_dano_moral.json`
- `outputs/prompt_refinement_sprint7/caso_02_rex_tributario.json`
- `outputs/prompt_refinement_sprint7/caso_03_sem_dispositivo_explicito.json`
- `outputs/prompt_refinement_sprint7/caso_04_clausula_contratual.json`
- `outputs/prompt_refinement_sprint7/caso_05_responsabilidade_estado.json`
- `outputs/prompt_refinement_sprint7/caso_06_prequestionamento.json`

Resumo observado (baseline):
- Casos executados: 6
- Casos com alerta Etapa 1: 6/6
- Casos com alerta Etapa 2: 6/6
- Casos com alerta Etapa 3: 6/6
- `completion_tokens` médio por chamada: 275.06
- `completion_tokens` máximo por chamada: 493

## 2) Padrões recorrentes e ajustes (7.1.2)

Padrões detectados:
1. **Etapa 2 sem `Conclusão e fundamentos` parseável** (rótulo variava do esperado).
2. **Falso positivo de recorrente na Etapa 1** (parser capturando frase narrativa em vez do nome).
3. **Seção III com súmulas não presentes na Etapa 2**.
4. **Aspas fora da transcrição literal** causando validação cruzada indevida na Etapa 3.

Ações aplicadas em `prompts/SYSTEM_PROMPT.md`:
- seção de compatibilidade obrigatória com parser;
- bloco técnico obrigatório no início da Etapa 1;
- formato da Etapa 2 padronizado para `Tema 1: ...` + `Conclusão e fundamentos: ...`;
- regra explícita de aspas apenas para transcrição da Seção II;
- vedação de súmula nova na Seção III.

## 3) Parâmetros ajustados (7.1.3)

Com base na distribuição real de tokens (completion máximo 493), foram ajustados defaults para reduzir variação e custo:
- `TEMPERATURE`: `0.1` -> `0.0`
- `MAX_TOKENS`: `4096` -> `2048`

Arquivos atualizados:
- `src/config.py`
- `.env.example`

## 4) Versionamento do prompt (7.1.4)

O prompt foi versionado para **1.1.0** com data **2026-02-10**, incluindo changelog no próprio arquivo:
- `prompts/SYSTEM_PROMPT.md`
- `SYSTEM_PROMPT.md`
