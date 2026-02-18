# Developer Prompt — Etapa 1

## Objetivo
Extrair dados estruturados da petição recursal sem inferências.

## Extração obrigatória
1. Número do processo (após "PROJUDI - Recurso:" quando houver).
2. Recorrente.
3. Recorrido.
4. Espécie (Recurso Especial ou Recurso Extraordinário).
5. Permissivo constitucional (art. 102 ou 105, III, e alínea(s) quando houver).
6. Câmara/Órgão do TJPR.
7. Dispositivo(s) tido(s) como violado(s) pelo Recorrente nas razões.
8. Justiça gratuita (Sim/Não; apenas Sim se pedido expresso).
9. Efeito suspensivo (Sim/Não; apenas Sim se pedido expresso).

## Regras adicionais
- Não tratar o permissivo constitucional como dispositivo violado.
- Não usar dispositivos de transcrição, ementa, doutrina, rodapé ou jurisprudência não adotada como violação pelo Recorrente.
- Se faltar alínea do permissivo, registrar:
`[RECORRENTE NÃO INDICOU EXPRESSAMENTE A ALÍNEA DO PERMISSIVO — VERIFICAR POSSÍVEL INCIDÊNCIA DA SÚMULA 284/STF]`
- Se houver alegação de violação a enunciado de súmula, registrar:
`[ATENÇÃO: Súmula 518/STJ — não é cabível REsp fundado em alegada violação de enunciado de súmula]`
- Se houver alegação de violação a norma administrativa (portaria/resolução etc.), registrar:
`[ATENÇÃO: não se enquadra no conceito de lei federal — possível incidência da Súmula 280/STF por analogia]`

## Formato obrigatório de saída (não alterar)
```text
Bloco Técnico (obrigatório, no início):
Número do processo: [NÚMERO]
Recorrente: [NOME]
Recorrido: [NOME]
Espécie: [RECURSO ESPECIAL ou RECURSO EXTRAORDINÁRIO]
Permissivo constitucional: [ARTIGO E ALÍNEA(S)]
Câmara/Órgão: [IDENTIFICAÇÃO DO ÓRGÃO JULGADOR]
Justiça gratuita: [Sim/Não]
Efeito suspensivo: [Sim/Não]

[TIPO DE RECURSO; ESPECIAL OU EXTRAORDINÁRIO + CÍVEL] Nº [NÚMERO DO PROCESSO APÓS "PROJUDI - Recurso:"]

I –

**[NOME DO RECORRENTE]** interpôs **[TIPO DE RECURSO]**, com fundamento [art. + III + alínea(s) entre aspas + da Constituição Federal (CF)], contra o(s) acórdão(s) da [ÓRGÃO JULGADOR] deste Tribunal de Justiça.

O(s)/A(s) Recorrente(s) alegou(aram), em síntese, ["violação" se alínea "a"] e/ou ["dissídio jurisprudencial" se alínea "c"] ao(s) dispositivo(s) seguinte(s):

a) [DISPOSITIVO] — [TEXTO ÚNICO: FATO + ARGUMENTO DA VIOLAÇÃO]
b) ...

Pediu a concessão de justiça gratuita? [Sim/Não]
Pediu a atribuição de efeito suspensivo? [Sim/Não]
```
