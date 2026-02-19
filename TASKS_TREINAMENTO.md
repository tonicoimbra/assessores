# TASKS_TREINAMENTO.md — Plano de Treinamento do Assessor.AI

> **Objetivo:** Tornar o agente altamente preciso na geração de minutas de admissibilidade, usando minutas de referência, feedback humano e avaliação contínua.
>
> **Resultado esperado:** Minutas geradas com excelência jurídica, formato 100% consistente, zero alucinações, e economia de tokens.

---

## Visão Geral da Arquitetura de Treinamento

```
┌─────────────────────────────────────────────────────────────────┐
│                    SISTEMA DE TREINAMENTO                       │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────┐  │
│  │ Base de       │   │ Seletor de   │   │ Injeção no Prompt  │  │
│  │ Minutas Gold  │──▶│ Similaridade │──▶│ (few-shot Etapa 3) │  │
│  │ (aprovadas)   │   │ (RAG leve)   │   │                    │  │
│  └──────────────┘   └──────────────┘   └────────────────────┘  │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────┐  │
│  │ Feedback      │   │ Auto-Eval    │   │ Regressão          │  │
│  │ do Assessor   │──▶│ por Rubrica  │──▶│ Contínua           │  │
│  │ (aceitar/rej) │   │              │   │                    │  │
│  └──────────────┘   └──────────────┘   └────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Sprint 1 — Base de Minutas de Referência (Gold Standard)

> **Meta:** Criar a infraestrutura para armazenar, indexar e recuperar minutas aprovadas.

### Tarefa 1.1 — Estrutura de Diretórios e Formato

- [ ] Criar diretório `minutas_referencia/` na raiz do projeto
- [ ] Criar subdiretórios por tipo de recurso:
  ```
  minutas_referencia/
  ├── recurso_especial/
  │   ├── admitido/
  │   └── inadmitido/
  ├── recurso_extraordinario/
  │   ├── admitido/
  │   └── inadmitido/
  └── metadata.json
  ```
- [ ] Definir formato padrão para cada minuta de referência: arquivo `.json` contendo:
  ```json
  {
    "id": "gold_001",
    "tipo_recurso": "recurso_especial",
    "decisao": "inadmitido",
    "materias": ["reexame de prova", "súmula 7/STJ"],
    "sumulas_aplicadas": ["7/STJ", "283/STF"],
    "tags": ["civel", "responsabilidade_civil", "dpvat"],
    "etapa1_resumo": "Recurso Especial com base no art. 105, III, 'a', CF...",
    "etapa2_resumo": "O acórdão fundamentou em reexame de matéria fática...",
    "minuta_completa": "RECURSO ESPECIAL CÍVEL Nº ...",
    "avaliacao_humana": "aprovada",
    "assessor_revisor": "nome_do_assessor",
    "data_aprovacao": "2026-02-19",
    "notas_revisao": "Minuta correta, sem ajustes necessários"
  }
  ```

### Tarefa 1.2 — Script de Importação de Minutas

- [ ] Criar `scripts/importar_minuta.py` para facilitar o cadastro:
  - Recebe o texto da minuta (Markdown ou texto puro)
  - Extrai automaticamente: tipo de recurso, decisão, súmulas mencionadas
  - Gera tags a partir das matérias controvertidas
  - Salva no formato JSON padrão em `minutas_referencia/`
  - Cria o embedding de texto para busca por similaridade (Tarefa 2.1)
- [ ] Suportar importação em lote de um diretório com minutas `.md` ou `.docx`

### Tarefa 1.3 — Curadoria Inicial (10-20 Minutas Gold)

- [ ] Solicitar ao usuário/assessor 10-20 minutas que considere exemplares
- [ ] Importar usando o script da Tarefa 1.2
- [ ] Garantir diversidade:
  - Mínimo 5 inadmitidos (com diferentes súmulas)
  - Mínimo 3 admitidos
  - Mínimo 2 admissão parcial
  - Cobrir: Súmulas 7, 211, 282, 283, 284, 126
- [ ] Validar formatação JSON e campos obrigatórios

---

## Sprint 2 — Seletor de Similaridade (RAG Leve)

> **Meta:** Dado um caso novo, encontrar a minuta de referência mais parecida para usar como exemplo.

### Tarefa 2.1 — Geração de Embeddings

- [ ] Criar `src/minuta_embeddings.py`:
  - Usar embeddings leves (e.g., `text-embedding-3-small` da OpenAI ou modelo local)
  - Gerar embedding para cada minuta gold baseado em:
    - Tipo de recurso + matérias controvertidas + súmulas
  - Salvar embeddings em `minutas_referencia/embeddings.json`
- [ ] Custo-eficiente: gerar embeddings uma única vez e cachear (não a cada request)

### Tarefa 2.2 — Buscador de Minuta Similar

- [ ] Criar `src/minuta_selector.py` com função:
  ```python
  def selecionar_minuta_referencia(
      tipo_recurso: str,
      materias: list[str],
      sumulas: list[str],
      top_k: int = 1
  ) -> dict | None:
  ```
- [ ] Critérios de seleção (por prioridade):
  1. **Mesmo tipo de recurso** (especial vs extraordinário) — eliminatório
  2. **Mesma decisão estimada** (admitido/inadmitido) — peso 3x
  3. **Súmulas em comum** — peso 2x
  4. **Matérias similares** — peso 1x via similaridade de embedding
- [ ] Fallback: se nenhuma minuta tiver similaridade > 0.5, retornar `None` (não forçar exemplo ruim)

### Tarefa 2.3 — Cache e Performance

- [ ] Pré-carregar embeddings na inicialização do app (não a cada request)
- [ ] Manter índice em memória (são apenas 10-20 minutas, não precisa de banco vetorial)
- [ ] Tempo máximo de seleção: <100ms

---

## Sprint 3 — Injeção no Prompt da Etapa 3

> **Meta:** Usar a minuta selecionada como exemplo (few-shot) no prompt da Etapa 3, sem ultrapassar o contexto.

### Tarefa 3.1 — Modificar Prompt da Etapa 3

- [ ] Editar `prompts/dev_etapa3.md` adicionando seção de referência:
  ```markdown
  ## Minuta de Referência (Exemplo)

  A minuta abaixo é um exemplo aprovado de caso similar. Use-a como
  referência de FORMATO, ESTILO e LINGUAGEM. NÃO copie o conteúdo —
  adapte para os fatos e fundamentos do caso atual.

  ---
  {minuta_referencia}
  ---
  ```
- [ ] Instrução explícita no prompt:
  - "Siga o formato e estilo da minuta de referência"
  - "NÃO copie dados/fatos — extraia exclusivamente das Etapas 1 e 2"
  - "A minuta de referência serve APENAS como modelo de escrita e estrutura"

### Tarefa 3.2 — Integrar no Pipeline

- [ ] Modificar `src/etapa3.py` para:
  1. Após Etapa 2, extrair: tipo de recurso, matérias, súmulas
  2. Chamar `selecionar_minuta_referencia()` com esses dados
  3. Se encontrar minuta similar, injetar no prompt da Etapa 3
  4. Se não encontrar (None), prosseguir sem exemplo (comportamento atual)
- [ ] Modificar `src/prompt_loader.py` para suportar variável `{minuta_referencia}` no template

### Tarefa 3.3 — Controle de Tokens

- [ ] Limitar a minuta de referência a **máximo 3.000 tokens** no prompt
- [ ] Se a minuta ultrapassar, truncar pela seção III (manter I e II como exemplo)
- [ ] Logar no metadata: `"minuta_referencia_usada": "gold_007"` ou `null`
- [ ] Adicionar ao `.env`: `ENABLE_MINUTA_REFERENCIA=true` (feature flag)

---

## Sprint 4 — Feedback do Assessor (Loop de Treinamento)

> **Meta:** Permitir que o assessor avalie cada minuta gerada e alimentar isso de volta no sistema.

### Tarefa 4.1 — UI de Feedback na Interface Web

- [ ] Após exibição do resultado, adicionar botões de avaliação:
  ```
  ┌──────────────────────────────────────┐
  │  Como avalia esta minuta?            │
  │                                      │
  │  [✅ Aprovada]  [⚠️ Parcial]  [❌ Reprovada] │
  │                                      │
  │  Comentários (opcional):             │
  │  ┌────────────────────────────────┐  │
  │  │                                │  │
  │  └────────────────────────────────┘  │
  │                                      │
  │  [💾 Salvar como Minuta Referência]  │
  └──────────────────────────────────────┘
  ```
- [ ] Campos:
  - `avaliacao`: aprovada | parcial | reprovada
  - `comentarios`: texto livre (o que estava errado, o que melhorar)
  - `salvar_como_gold`: checkbox (se aprovada, adicionar à base de referência)

### Tarefa 4.2 — API de Feedback

- [ ] Criar endpoint `POST /feedback` no `web_app.py`:
  ```python
  @app.post("/feedback/<job_id>")
  def feedback(job_id: str):
      avaliacao = request.form["avaliacao"]
      comentarios = request.form.get("comentarios", "")
      salvar_gold = request.form.get("salvar_gold") == "true"
      # Salvar feedback em outputs/feedback/
      # Se salvar_gold, importar automaticamente para minutas_referencia/
  ```
- [ ] Salvar feedback em `outputs/feedback/{timestamp}_{job_id}.json`

### Tarefa 4.3 — Auto-Promoção para Gold Standard

- [ ] Quando assessor marca "Aprovada" + "Salvar como Referência":
  1. Extrair tipo de recurso, matérias, súmulas da análise
  2. Gerar JSON no formato padrão (Tarefa 1.1)
  3. Gerar embedding (Tarefa 2.1)
  4. Adicionar a `minutas_referencia/` automaticamente
- [ ] A base cresce organicamente com o uso — sem intervenção manual

---

## Sprint 5 — Auto-Avaliação por Rubrica

> **Meta:** O próprio pipeline avalia a qualidade da minuta antes de entregar, usando critérios objetivos.

### Tarefa 5.1 — Rubrica de Avaliação Jurídica

- [ ] Criar `src/quality_rubric.py` com critérios mensuráveis:
  ```python
  RUBRICA = {
      "formato_correto": {
          "descricao": "Minuta segue seções I, II, III conforme modelo",
          "peso": 3,
          "check": "regex para I –, II –, III –"
      },
      "sem_alucinacao": {
          "descricao": "Não contém informações não presentes nas Etapas 1-2",
          "peso": 5,
          "check": "comparar dispositivos citados com Etapa 1"
      },
      "sumulas_corretas": {
          "descricao": "Súmulas da Seção III coincidem com Etapa 2",
          "peso": 4,
          "check": "extrair súmulas de ambas e comparar"
      },
      "campos_preenchidos": {
          "descricao": "Nenhum placeholder [NÃO CONSTA] na minuta final",
          "peso": 2,
          "check": "buscar padrão [NÃO CONSTA] na saída"
      },
      "decisao_coerente": {
          "descricao": "Decisão (admitir/inadmitir) coerente com óbices encontrados",
          "peso": 5,
          "check": "lógica: óbices em todos temas → inadmitir"
      }
  }
  ```

### Tarefa 5.2 — Pipeline de Auto-Avaliação

- [ ] Função `avaliar_minuta(resultado_etapa3, resultado_etapa1, resultado_etapa2) -> dict`:
  - Retorna score 0-100 com detalhes por critério
  - Threshold mínimo configurável: `QUALITY_MIN_SCORE=70`
- [ ] Integrar na pipeline (após Etapa 3):
  - Se score < threshold: logar alerta + marcar nos metadata
  - Se score >= threshold: normalidade
- [ ] Incluir no relatório de auditoria

### Tarefa 5.3 — Comparação com Minuta Gold

- [ ] Se uma minuta de referência foi usada, comparar:
  - Estrutura da saída vs. estrutura da referência
  - Percentual de aderência ao formato
  - Desvios significativos (adicionar ao alerta)

---

## Sprint 6 — Dashboard de Qualidade e Métricas

> **Meta:** Visibilidade contínua sobre a qualidade das minutas geradas.

### Tarefa 6.1 — Métricas de Treinamento

- [ ] Criar `src/training_metrics.py`:
  - Taxa de aprovação por assessor (%)
  - Score médio da auto-avaliação por período
  - Minutas gold adicionadas vs. total gerado
  - Top 5 motivos de reprovação (do feedback)
  - Custo médio por análise (tokens × preço)

### Tarefa 6.2 — Endpoint de Dashboard

- [ ] Criar `GET /dashboard` no `web_app.py`:
  - Cards com métricas resumidas
  - Gráfico simples de evolução de qualidade
  - Lista das últimas minutas com avaliação
- [ ] Acessar dados de `outputs/feedback/` e metadata das análises

### Tarefa 6.3 — Alertas de Regressão

- [ ] Se taxa de aprovação cair abaixo de 80% na última semana: alerta
- [ ] Se score auto-avaliação médio cair mais de 10 pontos: alerta
- [ ] Integrar com `src/regression_alerts.py` (já existente)

---

## Sprint 7 — Refinamento do Prompt por Dados

> **Meta:** Usar o feedback acumulado para refinar automaticamente o SYSTEM_PROMPT.

### Tarefa 7.1 — Análise de Padrões de Erro

- [ ] Script `scripts/analisar_erros.py`:
  - Ler todos os feedbacks de `outputs/feedback/`
  - Categorizar erros mais frequentes (alucinação, formato, súmula errada, etc.)
  - Gerar relatório de recomendações para ajuste do prompt

### Tarefa 7.2 — Regras de Anti-Alucinação Específicas

- [ ] Baseado nos erros encontrados na Tarefa 7.1:
  - Adicionar regras específicas no SYSTEM_PROMPT.md
  - Exemplos: "Nunca cite Súmula X quando o tema for Y"
  - Documentar em `prompts/PROMPT_CHANGELOG.md`

### Tarefa 7.3 — Testes de Regressão do Prompt

- [ ] Sempre que alterar o SYSTEM_PROMPT:
  1. Rodar pipeline contra as N minutas gold (golden_baseline.py)
  2. Comparar scores com a baseline anterior
  3. Só fazer deploy se score >= baseline
- [ ] Automatizar via script `scripts/test_prompt_regression.py`

---

## Sprint 8 — Otimizações de Custo e Velocidade

> **Meta:** Reduzir custo por análise mantendo qualidade.

### Tarefa 8.1 — Cache Semântico de Temas Recorrentes

- [ ] Ativar `ENABLE_CACHING=true` no `.env`
- [ ] Configurar `src/cache_manager.py` para cachear:
  - Respostas de Etapa 2 quando tema/acórdão são idênticos
  - Trechos de transcrição reutilizáveis
- [ ] Medir economia real de tokens com cache ativo

### Tarefa 8.2 — Modelo Híbrido Otimizado

- [ ] Testar configuração:
  - **Classificação + Chunks**: modelo leve (Qwen3 30B ou 72B, ~$0.01/M)
  - **Etapa 2 e 3 (análise jurídica)**: modelo parrudo (Qwen3 235B, $0.07/$0.46)
- [ ] Medir: custo real, qualidade (score rubrica), tempo
- [ ] Documentar comparação em `docs/benchmark_modelos.md`

### Tarefa 8.3 — Processamento Paralelo da Etapa 2

- [ ] Ativar `ENABLE_PARALLEL_ETAPA2=true`
- [ ] Testar: temas analisados em paralelo (múltiplos chunks simultâneos)
- [ ] Medir redução de tempo total da pipeline

---

## Resumo de Entregas por Sprint

| Sprint | Entregas | Prioridade |
|--------|----------|------------|
| **1** | Base de minutas gold + formato + importador | 🔴 Crítica |
| **2** | Seletor de similaridade (RAG leve) | 🔴 Crítica |
| **3** | Injeção no prompt Etapa 3 (few-shot) | 🔴 Crítica |
| **4** | UI de feedback + loop de treinamento | 🟡 Alta |
| **5** | Auto-avaliação por rubrica | 🟡 Alta |
| **6** | Dashboard de qualidade | 🟢 Média |
| **7** | Refinamento de prompt por dados | 🟢 Média |
| **8** | Otimizações de custo e velocidade | 🟢 Média |

---

## Dependências e Pré-Requisitos

- **Sprint 1** → pode ser iniciada imediatamente
- **Sprint 2** → depende da Sprint 1 (precisa das minutas gold)
- **Sprint 3** → depende da Sprint 2 (precisa do seletor)
- **Sprint 4** → pode ser iniciada em paralelo com Sprint 2-3
- **Sprint 5** → pode ser iniciada em paralelo com Sprint 3-4
- **Sprint 6** → depende de Sprint 4 e 5 (precisa de dados de feedback)
- **Sprint 7** → depende de Sprint 6 (precisa de dados acumulados)
- **Sprint 8** → pode ser iniciada a qualquer momento

---

## Métricas de Sucesso (KPIs)

| Métrica | Baseline Atual | Meta Sprint 3 | Meta Sprint 6 |
|---------|---------------|---------------|---------------|
| Taxa de aprovação do assessor | ~0% (nenhuma prestou) | 60% | 85% |
| Score auto-avaliação | N/A | 70/100 | 85/100 |
| Custo por análise | ~$0.10 | ~$0.01 | ~$0.01 |
| Tempo por análise | ~3min | ~2min | ~1.5min |
| Minutas gold na base | 0 | 15 | 50+ |
| Alucinações detectadas | Alta | <10% | <2% |
