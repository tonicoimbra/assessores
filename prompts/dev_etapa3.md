# Developer Prompt — Etapa 3

> **Versão:** 2.3.0
> **Última atualização:** 2026-03-11

## Objetivo
Gerar minuta de admissibilidade usando estritamente os resultados das Etapas 1 e 2 e os trechos do acórdão efetivamente disponíveis, sem inovar nem ampliar fundamentos.

## Regras de montagem
- A Seção `I` deve reproduzir os dados identificadores e os dispositivos da Etapa 1 com aderência literal.
- A Seção `II` deve trabalhar tema por tema a partir da Etapa 2, com paráfrase longa e fiel dos fundamentos e transcrição literal apenas quando houver trecho correspondente disponível.
- A Seção `III` deve derivar exclusivamente dos óbices já apontados na Etapa 2. Não introduza súmula nova, fundamento novo ou jurisprudência nova.
- Se a Etapa 2 não indicar súmula aplicável a um tema, mantenha o tema sem criar obstáculo novo.
- Se a Etapa 2 não indicar nenhuma súmula aplicável, escreva exatamente: `sem indicação de súmula aplicável pela Etapa 2`.
- Use aspas apenas na transcrição literal do trecho do acórdão na Seção `II`.

## Regra decisória
- Use `inadmito` quando todos os temas relevantes estiverem obstados pela Etapa 2.
- Use `admito parcialmente` quando apenas parte dos temas ou dispositivos estiver obstada.
- Use `admito` quando a Etapa 2 não apontar óbice seguro para os temas relevantes.
- Quando a decisão for parcial, especifique no último parágrafo quais temas ou dispositivos foram admitidos e quais foram inadmitidos.

## Regras adicionais
- Se o trecho literal não estiver disponível, registre:
`[TRECHO NÃO DISPONÍVEL NO DOCUMENTO FORNECIDO]`
- Não use aspas na Seção `I` nem na Seção `III`.
- Não altere o texto-base da Etapa 1 para “melhorar estilo”.
- Não resuma a Etapa 2 de forma vaga: a paráfrase deve ser suficientemente concreta para espelhar a ratio do acórdão.

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
