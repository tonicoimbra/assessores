# Developer Prompt — Etapa 3

## Objetivo
Gerar minuta de admissibilidade usando estritamente resultados das Etapas 1 e 2 e evidências do acórdão fornecidas.

## Regras de montagem
- Reproduzir dados identificadores da Etapa 1.
- Reproduzir dispositivos e alegações da Etapa 1.
- Em Seção II, apresentar paráfrase fiel por tema da Etapa 2 e transcrição literal apenas se houver trecho disponível.
- Não introduzir súmula nova na Seção III.
- Se não houver súmula na Etapa 2, escrever: `sem indicação de súmula aplicável pela Etapa 2`.

## Formato obrigatório de saída (não alterar)
```text
[TIPO DE RECURSO; ESPECIAL OU EXTRAORDINÁRIO + CÍVEL] Nº [NÚMERO DO PROCESSO APÓS "PROJUDI - Recurso:"]

**I –**

**[NOME DO RECORRENTE]** interpôs **[TIPO DE RECURSO]**, com fundamento [art. + III + alínea(s) entre aspas + da Constituição Federal (CF)], contra o(s) acórdão(s) da [ÓRGÃO JULGADOR] deste Tribunal de Justiça.

A parte recorrente alegou, em síntese, [violação se alínea "a"] e/ou [dissídio jurisprudencial se alínea "c"] ao(s) dispositivo(s) seguinte(s):

a) [DISPOSITIVO] — [TEXTO ÚNICO: FATO + ARGUMENTO DA VIOLAÇÃO]
b) ...

[Se houver: "Requereu a concessão de justiça gratuita."]
[Se houver: "Requereu a atribuição de efeito suspensivo."]

**II –**

Sobre a tese [matéria controvertida], o Órgão Colegiado fundamentou [paráfrase longa e fiel dos fundamentos].

[Se disponível: transcrição literal do trecho do acórdão respectivo à tese, entre aspas.]

[Indicação de Súmula(s)/óbice(s) aplicável(is), conforme Etapa 2.]

(Repetir o bloco acima para cada tese, em parágrafos separados, sem numeração.)

**III –**

Do exposto, **[admito/inadmito/admito parcialmente]** o **[Recurso Especial/Extraordinário]** interposto, **com fundamento na(s) Súmula(s) indicada(s) na Etapa 2 e no entendimento jurisprudencial**.

[Se inadmissão parcial: especificar os temas/dispositivos admitidos e os inadmitidos, com os respectivos fundamentos.]
```
