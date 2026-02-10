# Diretrizes do Prompt de IA

O arquivo [`SYSTEM_PROMPT.md`](../SYSTEM_PROMPT.md) contém o prompt completo do agente. Este documento resume as diretrizes principais.

## Identidade

O agente atua como especialista em Direito Processual Civil brasileiro, focado em exame de admissibilidade de Recurso Especial e Extraordinário.

## Regras anti-alucinação

As regras mais importantes do prompt:

- **Não alucinar.** Não criar, não inventar, não deduzir.
- **Fonte exclusiva:** apenas os documentos fornecidos (PDFs do recurso e acórdão).
- **Lacunas:** se algo não consta no documento, usar exatamente `[NÃO CONSTA NO DOCUMENTO]`.
- **Roteiro fixo:** sempre seguir Etapa 1 → 2 → 3, sem etapas adicionais.

## Pipeline de 3 etapas

### Etapa 1 — Análise da Petição do Recurso

**Entrada:** texto da petição do recurso.

**Extrair:** número do processo, recorrente, recorrido, espécie do recurso, permissivo constitucional, câmara cível, dispositivos violados, pedido de justiça gratuita e efeito suspensivo.

**Regra:** para cada dispositivo, redigir texto único com dispositivo + fato + argumento jurídico.

### Etapa 2 — Análise do Acórdão

**Entrada:** texto do acórdão + dados da Etapa 1.

**Para cada tema:** identificar matéria controvertida, conclusão/fundamentos (paráfrase), base vinculante, e óbices/súmulas aplicáveis.

**Óbices permitidos:**
- STJ: Súmulas 5, 7, 13, 83, 126, 211, 518
- STF: Súmulas 279, 280, 281, 282, 283, 284, 356, 735

### Etapa 3 — Minuta de Decisão

**Entrada:** resultados das Etapas 1 e 2 + texto do acórdão (para transcrições literais).

**Formato:** seções I (dados do recurso), II (temas com paráfrase + transcrição), III (decisão admito/inadmito).

**Regra:** usar apenas dados já armazenados nas etapas anteriores, sem inovar.

## Convenções de formatação

- Abreviar artigo como `art.`
- Não escrever inciso ou alínea por extenso (usar III, a, c)
- Siglas: nome completo na primeira menção
- Recorrente e Recorrido sempre com inicial maiúscula
- Desinência de gênero e número adequada

## Manutenção do prompt

O `SYSTEM_PROMPT.md` é versionado com tabela de changelog ao final do arquivo. Alterações no prompt não requerem mudanças no código.
